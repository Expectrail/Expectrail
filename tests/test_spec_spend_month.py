"""Offline regression checks for spec sender caps and the opt-in model month (#267)."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from agents import feedback, spark_open, sam_observations
from expectrail import providers, spec_writer, spend
from expectrail.contracts import ContractError

REPO = Path(__file__).resolve().parent.parent
ANSWER = {"choices": [{"message": {"content": '{"unsupported": "fixture"}'}}]}


class SpecSpendTest(unittest.TestCase):
    def setUp(self):
        self.usage = mock.patch.dict(sam_observations._usage,
                                    dict(requests=0, images=0, videoFrames=0, reservedUsd=0.0), clear=True)
        self.usage.start()
        self.addCleanup(self.usage.stop)
        self.env = mock.patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        spend.reset_for_tests()
        self.addCleanup(spend.reset_for_tests)

    def senders(self):
        os.environ["MODEL_API_KEY"] = "test-not-a-key"
        provider, _ = spec_writer.provider_transport("ollama")
        return (spec_writer.http_transport, spec_writer.open_transport(key="test-not-a-key"),
                provider, feedback.openai_transport("https://example.invalid/v1", "test-not-a-key"))

    def test_every_sender_direct_and_wrapped_refuses_without_a_cap(self):
        body = spec_writer.request_body("x", "fixture")
        for sender in self.senders():
            for transport in (sender, spark_open.counting(sender, [], "test")):
                with self.subTest(sender=sender, wrapped=transport is not sender), \
                        mock.patch("urllib.request.urlopen") as network:
                    spend.reset_for_tests()
                    with self.assertRaises(spend.BudgetStop) as stopped:
                        transport(body)
                    self.assertEqual(stopped.exception.role, "spec")
                    self.assertIn("EXPECTRAIL_SPEC_USD_CAP", str(stopped.exception))
                    network.assert_not_called()
                    doc = spend.build_job_budget("missing-cap")
                    self.assertEqual(doc["phases"][0]["role"], "spec")
                    self.assertEqual(doc["phases"][0]["requests"], 0)
                    self.assertIsNotNone(doc["phases"][0]["stopped"])

    def test_every_sender_holds_once_before_a_wrapped_draft_and_blocks_the_next(self):
        os.environ["EXPECTRAIL_SPEC_USD_CAP"] = "0.05"
        for sender in self.senders():
            spend.reset_for_tests()
            sent = []

            def network(*args, **kwargs):
                sent.append(spend.METER.snapshot_roles()["spec"]["requests"])
                return io.BytesIO(json.dumps(ANSWER).encode())

            with self.subTest(sender=sender), mock.patch("urllib.request.urlopen", side_effect=network):
                transport = spark_open.counting(sender, [], "test")
                self.assertIsNone(spec_writer.draft("x", transport=transport)[0])
                with self.assertRaises(spend.BudgetStop):
                    spec_writer.draft("x", transport=transport)
                self.assertEqual(sent, [1])
                self.assertEqual(spend.METER.snapshot_roles()["spec"]["reserved"], 0.05)

    def test_standins_are_uncapped_until_a_cap_is_set_and_retries_are_counted(self):
        calls = []

        def fixture(body):
            calls.append(body)
            if len(calls) % 2:
                raise spec_writer.SpecDraftError("HTTP 400: response_format")
            return ANSWER

        wrapped = spark_open.counting(fixture, [], "fixture")
        spec_writer.draft("x", transport=wrapped)
        self.assertEqual(len(calls), 2)
        self.assertEqual(spend.METER.snapshot_roles()["spec"]["requests"], 0)
        os.environ["EXPECTRAIL_SPEC_USD_CAP"] = "0.1"
        spec_writer.draft("x", transport=wrapped)
        self.assertEqual(spend.METER.snapshot_roles()["spec"]["requests"], 2)
        with self.assertRaises(spend.BudgetStop):
            spec_writer.draft("x", transport=wrapped)
        self.assertEqual(len(calls), 4)

    def test_real_schema_fallback_and_provider_retry_hold_each_attempt(self):
        body = spec_writer.request_body("x", "fixture")
        for sender in self.senders():
            spend.reset_for_tests()
            os.environ["EXPECTRAIL_SPEC_USD_CAP"] = "0.05"
            with self.subTest(sender=sender), mock.patch("urllib.request.urlopen", side_effect=
                    urllib.error.HTTPError("https://example.invalid", 400, "bad", {},
                                           io.BytesIO(b"response_format schema"))) as network:
                with self.assertRaises(spend.BudgetStop):
                    spec_writer.draft("x", transport=sender)
                self.assertEqual(network.call_count, 1)
        spend.reset_for_tests()
        sender, _ = spec_writer.provider_transport("ollama")
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
                "https://example.invalid", 503, "retry", {}, io.BytesIO(b"retry"))) as network, \
                mock.patch("expectrail.providers.time.sleep"):
            with self.assertRaises(spend.BudgetStop):
                sender(body)
            self.assertEqual(network.call_count, 1)

    def test_invalid_caps_never_send_and_are_named_stops(self):
        for cap in ("NaN", "inf", "-1", "not-an-amount"):
            os.environ["EXPECTRAIL_SPEC_USD_CAP"] = cap
            for sender in self.senders():
                with self.subTest(cap=cap, sender=sender), mock.patch("urllib.request.urlopen") as network:
                    with self.assertRaises(spend.BudgetStop):
                        sender(spec_writer.request_body("x", "fixture"))
                    network.assert_not_called()

    def test_feedback_classification_is_outside_the_spec_cap(self):
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(ANSWER).encode())):
            feedback.openai_transport("https://example.invalid", "test-not-a-key")(
                feedback.classify_body([], "fixture"))
        self.assertEqual(spend.METER.snapshot_roles()["spec"]["requests"], 0)

    def test_budget_spec_role_round_trips_and_reader_checks_its_phase(self):
        os.environ["EXPECTRAIL_SPEC_USD_CAP"] = "0.1"
        spec_writer.draft("x", transport=lambda body: ANSWER)
        doc = spend.build_job_budget("spec-job")
        self.assertEqual(doc["capsUsd"]["spec"], 0.1)
        self.assertEqual(doc["phases"][0]["phase"], "drafting")
        self.assertEqual(doc["totalReservedUsd"], 0.05)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "budget.json"
            spend.write_job_budget(doc, path)
            self.assertEqual(spend.read_job_budget(path), doc)
            doc["phases"][0]["phase"] = "observing"
            path.write_text(json.dumps(doc))
            with self.assertRaises(ContractError):
                spend.read_job_budget(path)


class ModelMonthTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        spend.reset_for_tests()
        self.addCleanup(spend.reset_for_tests)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "month.json"
        self.now = datetime(2026, 11, 15, tzinfo=timezone.utc)

    def admit(self, role="spec", cap=10, **kwargs):
        return spend.admit_model_month(role, cap, path=self.path, now=self.now, **kwargs)

    def test_opt_in_and_every_role_reserves_its_whole_cap_once(self):
        for role in spend.MODEL_ROLES:
            self.assertIsNone(spend.admit_model_month(role, 10))
        self.assertFalse(self.path.exists())
        os.environ[spend.MODEL_LEDGER_ENV] = str(self.path)
        for role in spend.MODEL_ROLES:
            os.environ[spend.CAP_ENV[role]] = "10"
            spend.hold(role, live=True)
            spend.hold(role, live=True)
        doc = spend.read_model_month(self.path)
        self.assertEqual(doc["spentUsd"], 40)
        self.assertEqual([entry["role"] for entry in doc["entries"]], list(spend.MODEL_ROLES))
        self.assertEqual([entry["reservedUsd"] for entry in doc["entries"]], [10] * 4)

    def test_same_job_in_new_process_reserves_again_but_cap_increase_only_reserves_delta(self):
        self.admit(job_id="job")
        self.admit(job_id="job")
        self.admit(cap=15, job_id="job")
        self.assertEqual(spend.read_model_month(self.path)["spentUsd"], 15)
        spend.reset_for_tests()
        self.admit(cap=15, job_id="job")
        self.assertEqual(spend.read_model_month(self.path)["spentUsd"], 30)

    def test_invalid_even_old_ledgers_and_unreadable_paths_stop_without_replacement(self):
        malformed = ("", " ", "{broken", "null", "[]", '{"format":1,"format":2}')
        valid = self.admit()
        invalid = [dict(valid, spentUsd=100), dict(valid, month="2026-99"),
                   dict(valid, spentUsd=float("nan")), dict(valid, month="2026-10", entries=[{}])]
        for content in (*malformed, *(json.dumps(doc) for doc in invalid)):
            self.path.write_text(content)
            with self.subTest(content=content), self.assertRaises(spend.BudgetStop) as stopped:
                self.admit()
            self.assertIn("model month ledger", str(stopped.exception))
            self.assertEqual(self.path.read_text(), content)
        self.path.unlink()
        self.path.mkdir()
        with self.assertRaises(spend.BudgetStop) as stopped:
            self.admit()
        self.assertIn("unreadable or invalid", str(stopped.exception))

    def test_disappeared_ledger_is_a_stop_instead_of_an_empty_month(self):
        self.admit()
        self.path.unlink()
        with self.assertRaises(spend.BudgetStop) as stopped:
            self.admit()
        self.assertIn("previously reserved ledger is missing", str(stopped.exception))
        self.assertFalse(self.path.exists())

    def test_month_rollover_and_future_ledger(self):
        self.admit()
        self.now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self.admit(cap=5)
        self.assertEqual(spend.read_model_month(self.path)["spentUsd"], 5)
        self.assertEqual(spend.read_model_month(self.path)["month"], "2026-12")
        self.now = datetime(2026, 11, 15, tzinfo=timezone.utc)
        with self.assertRaises(spend.BudgetStop):
            self.admit()

    def test_two_real_processes_cannot_both_pass_the_combined_limit(self):
        code = '''import sys
from pathlib import Path
from expectrail.spend import admit_model_month, BudgetStop
try:
    admit_model_month(sys.argv[2], 150, path=Path(sys.argv[1]), job_id=sys.argv[2])
    print('admitted')
except BudgetStop:
    print('stopped')
'''
        procs = [subprocess.Popen([sys.executable, "-c", code, str(self.path), role], cwd=REPO,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for role in ("glimmer", "muse")]
        outputs = []
        for proc in procs:
            out, err = proc.communicate(timeout=30)
            self.assertEqual(proc.returncode, 0, err)
            outputs.append(out.strip())
        self.assertEqual(sorted(outputs), ["admitted", "stopped"])
        self.assertEqual(spend.read_model_month(self.path)["spentUsd"], 150)

    def test_failed_atomic_write_preserves_ledger_and_can_be_retried(self):
        self.admit()
        before = self.path.read_bytes()
        with mock.patch("expectrail.spend.os.replace", side_effect=OSError("write failed")):
            with self.assertRaises(spend.BudgetStop):
                self.admit(role="muse")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["month.json", "month.json.lock"])
        self.admit(role="muse")
        self.assertEqual(spend.read_model_month(self.path)["spentUsd"], 20)

    def test_month_refusal_prevents_each_role_request_and_records_the_stop(self):
        self.admit(role="muse", cap=200)
        os.environ[spend.MODEL_LEDGER_ENV] = str(self.path)
        # The integration uses the actual current UTC month, like all real requests.
        doc = spend.read_model_month(self.path)
        doc["month"] = spend.month_of()
        self.path.write_text(json.dumps(doc))
        spend.reset_for_tests()
        for role in spend.MODEL_ROLES:
            os.environ[spend.CAP_ENV[role]] = "1"
            with self.subTest(role=role), self.assertRaises(spend.BudgetStop):
                spend.hold(role, live=True)
            row = spend.METER.snapshot_roles()[role]
            self.assertEqual(row["requests"], 0)
            self.assertIn("$200", row["stopped"])


if __name__ == "__main__":
    unittest.main()
