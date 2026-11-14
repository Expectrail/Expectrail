"""Spend caps for Glimmer, Muse and triage, the job budget, and the vision month (#267).

Vision's own cap stays in agents.sam_observations. These tests hold that the other roles count a
request before it is sent and stop with a reason, that the budget and capability records round-trip,
and that a run whose cap would pass $200 in the month is refused before anything is sent.
No live call is made: transports and ``muse`` are stand-ins, and keys are throwaways.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import agents.glimmer_client as gl
import agents.sam_observations as sam
from agents.sam_observations import MetaSamClient
from expectrail.contracts import ContractError, load
from expectrail.providers import PROVIDER_DEFAULTS
from expectrail.spend import (
    LEDGER_ENV,
    RESERVE_USD,
    VISION_MONTH_LIMIT_USD,
    BudgetStop,
    admit_vision_month,
    build_job_budget,
    read_job_budget,
    read_provider_capability,
    read_vision_month,
    reset_for_tests,
    write_job_budget,
    write_provider_capability,
)
from harness.run import REPO
from tests.test_sam import png_bytes

EXAMPLES = REPO / "contracts" / "examples"
CAP_KEYS = (
    "EXPECTRAIL_SAM_USD_CAP",
    "EXPECTRAIL_GLIMMER_USD_CAP",
    "EXPECTRAIL_MUSE_USD_CAP",
    "EXPECTRAIL_TRIAGE_USD_CAP",
    LEDGER_ENV,
    "EXPECTRAIL_JOB_ID",
)


def _reply_empty() -> tuple[bytes, str]:
    body = json.dumps({"choices": [{"message": {"content": json.dumps({"objects": []})}}]})
    return body.encode(), "application/json"


class _SpendCase(unittest.TestCase):
    def setUp(self):
        reset_for_tests()
        self._usage = dict(sam._usage)
        sam._usage.update({"requests": 0, "images": 0, "videoFrames": 0, "reservedUsd": 0.0})
        saved = {key: os.environ.get(key) for key in CAP_KEYS}
        for key in CAP_KEYS:
            os.environ.pop(key, None)

        def restore() -> None:
            sam._usage.update(self._usage)
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            reset_for_tests()

        self.addCleanup(restore)


class RecordTest(_SpendCase):
    def test_the_examples_load_and_every_provider_has_a_record(self):
        budget = read_job_budget(EXAMPLES / "job-budget.json")
        self.assertEqual(budget["totalReservedUsd"], 1.35)
        self.assertEqual(budget["visionMonth"]["limitUsd"], VISION_MONTH_LIMIT_USD)
        month = read_vision_month(EXAMPLES / "vision-month.json")
        self.assertEqual(month["spentUsd"], 0.5)
        folder = EXAMPLES / "provider-capabilities"
        self.assertEqual({path.stem for path in folder.glob("*.json")}, set(PROVIDER_DEFAULTS))
        for name, defaults in PROVIDER_DEFAULTS.items():
            doc = read_provider_capability(folder / f"{name}.json")
            self.assertEqual((doc["provider"], doc["protocol"]), (name, defaults["protocol"]))
            roles = {role["role"]: role for role in doc["roles"]}
            if name == "fireworks":
                self.assertEqual(roles["glimmer"]["models"], [defaults["default_model"]])
            elif name != "meta":
                self.assertEqual(roles["triage"]["models"], [defaults["default_model"]])
            else:
                self.assertEqual(set(roles), {"vision", "triage", "muse"})

    def test_writer_and_reader_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            budget = read_job_budget(EXAMPLES / "job-budget.json")
            write_job_budget(budget, root / "budget.json")
            self.assertEqual(read_job_budget(root / "budget.json"), budget)
            capability = read_provider_capability(EXAMPLES / "provider-capabilities" / "openai.json")
            write_provider_capability(capability, root / "openai.json")
            self.assertEqual(read_provider_capability(root / "openai.json"), capability)

    def test_a_record_that_does_not_add_up_or_is_not_json_is_refused(self):
        budget = read_job_budget(EXAMPLES / "job-budget.json")
        drifted = json.loads(json.dumps(budget))
        drifted["phases"][2]["phase"] = "observing"  # muse is the fixing phase
        with self.assertRaises(ContractError):
            write_job_budget(drifted)
        wrong_total = json.loads(json.dumps(budget))
        wrong_total["totalReservedUsd"] = 0
        with self.assertRaises(ContractError):
            write_job_budget(wrong_total)
        capability = read_provider_capability(EXAMPLES / "provider-capabilities" / "meta.json")
        bad_hold = json.loads(json.dumps(capability))
        bad_hold["roles"][0]["reserveUsd"] = 9
        with self.assertRaises(ContractError):
            write_provider_capability(bad_hold)
        bad_env = json.loads(json.dumps(capability))
        bad_env["roles"][1]["capEnv"] = "EXPECTRAIL_OTHER_USD_CAP"
        with self.assertRaises(ContractError):
            write_provider_capability(bad_env)
        twice = json.loads(json.dumps(capability))
        twice["roles"].append(twice["roles"][0])
        with self.assertRaises(ContractError):
            write_provider_capability(twice)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text('{"format": "expectrail.job-budget/v1", "format": "no"}\n', encoding="utf-8")
            with self.assertRaises(ContractError):
                read_job_budget(path)
            path.write_text(json.dumps({**budget, "totalReservedUsd": float("nan")}), encoding="utf-8")
            # json.dumps refuses NaN by default; write the token by hand.
            text = (EXAMPLES / "job-budget.json").read_text(encoding="utf-8").replace("1.35", "NaN", 1)
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ContractError):
                read_job_budget(path)

    def test_what_this_process_held_is_the_job_budget(self):
        from expectrail.spend import hold

        with mock.patch.dict(os.environ, {
            "EXPECTRAIL_GLIMMER_USD_CAP": "1",
            "EXPECTRAIL_MUSE_USD_CAP": "2",
            "EXPECTRAIL_TRIAGE_USD_CAP": "1",
        }):
            hold("glimmer", live=False)
            hold("muse", live=False)
            hold("triage", live=False)
            sam._usage["reservedUsd"] = 0.25
            sam._usage["requests"] = 100
            doc = build_job_budget("job-1")
        by_role = {phase["role"]: phase for phase in doc["phases"]}
        self.assertEqual(by_role["vision"]["phase"], "observing")
        self.assertEqual(by_role["vision"]["reservedUsd"], 0.25)
        self.assertEqual(by_role["glimmer"]["reservedUsd"], RESERVE_USD["glimmer"])
        self.assertEqual(by_role["muse"]["phase"], "fixing")
        self.assertEqual(by_role["muse"]["reservedUsd"], RESERVE_USD["muse"])
        self.assertEqual(by_role["triage"]["phase"], "triaging")
        self.assertAlmostEqual(doc["totalReservedUsd"], 0.25 + 0.05 + 1.0 + 0.05)
        self.assertIsNone(doc["stopped"])
        self.assertFalse(doc["visionMonth"]["admitted"])


class GlimmerCapTest(_SpendCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.png = Path(self.tmp.name) / "f.png"
        self.png.write_bytes(png_bytes(8, 8, 1))
        self.sent: list = []

    def transport(self, body):
        self.sent.append(body)
        return _reply_empty()

    def test_a_stand_in_with_no_cap_still_runs_and_a_bad_cap_is_not_no_cap(self):
        client = gl.GlimmerClient(transport=self.transport, key="k", sleep=lambda _s: None)
        self.assertEqual(client.segment(self.png, "coin"), [])
        self.assertEqual(len(self.sent), 1)
        with mock.patch.dict(os.environ, {"EXPECTRAIL_GLIMMER_USD_CAP": "lots"}):
            with self.assertRaises(sam.SamError) as refused:
                client.segment(self.png, "coin")
        self.assertEqual(refused.exception.kind, "budget")
        self.assertIn("must be an amount", str(refused.exception))
        self.assertNotIn("no spend cap", str(refused.exception))
        self.assertEqual(len(self.sent), 1)

    def test_the_request_past_one_hold_is_not_sent(self):
        client = gl.GlimmerClient(transport=self.transport, key="k", sleep=lambda _s: None)
        with mock.patch.dict(os.environ, {"EXPECTRAIL_GLIMMER_USD_CAP": "0.05"}):
            client.segment(self.png, "coin")
            with self.assertRaises(sam.SamError) as stopped:
                client.segment(self.png, "coin")
        self.assertEqual(stopped.exception.kind, "budget")
        self.assertIn("was not sent", str(stopped.exception))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(client.calls, 1)

    def test_the_real_sender_with_no_cap_does_not_open_a_connection(self):
        opened: list = []

        def opened_anyway(*_args, **_kwargs):
            opened.append(1)
            raise AssertionError("a request was opened")

        with mock.patch.object(gl.urllib.request, "urlopen", side_effect=opened_anyway), \
                mock.patch.dict(os.environ, {"META_API_KEY": ""}, clear=False):
            with self.assertRaises(sam.SamError) as refused:
                gl.GlimmerClient(key="test-not-a-key")._http({})
            with self.assertRaises(sam.SamError) as warmed:
                gl.warm(key="test-not-a-key", opener=urllib.request.urlopen)
        self.assertEqual(refused.exception.kind, "budget")
        self.assertIn("Nothing is sent", str(refused.exception))
        self.assertEqual(warmed.exception.kind, "budget")
        self.assertEqual(opened, [])


class MuseCapTest(_SpendCase):
    def test_nothing_starts_without_a_cap_and_the_second_invocation_stops(self):
        from agents.sandbox import run_muse

        fake = subprocess.CompletedProcess(["muse"], 0, "ok", "")
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_MUSE_GATEWAY": "off"}), \
                mock.patch("agents.sandbox.subprocess.run", return_value=fake) as run:
            with self.assertRaises(BudgetStop) as missing:
                run_muse("hi", work=Path(tmp), timeout=5, sandboxed=False)
            self.assertIn("Nothing is sent", str(missing.exception))
            run.assert_not_called()
            os.environ["EXPECTRAIL_MUSE_USD_CAP"] = "1"
            first, _meta = run_muse("hi", work=Path(tmp), timeout=5, sandboxed=False)
            self.assertEqual(first.returncode, 0)
            with self.assertRaises(BudgetStop) as stopped:
                run_muse("hi", work=Path(tmp), timeout=5, sandboxed=False)
        self.assertIn("was not sent", str(stopped.exception))
        self.assertEqual(run.call_count, 1)
        self.assertFalse(issubclass(BudgetStop, RuntimeError))


class TriageCapTest(_SpendCase):
    def _docs(self):
        return (
            load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
            load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
            load(REPO / "harness" / "routes" / "smoke.json", "route"),
        )

    def test_wonder_and_byo_send_nothing_without_a_cap(self):
        from agents.triage import call_byo, call_wonder, triage

        with mock.patch("agents.triage.urllib.request.urlopen",
                        side_effect=AssertionError("wonder was opened")):
            with self.assertRaises(BudgetStop) as wonder:
                call_wonder("what broke", "test-not-a-key")
        self.assertIn("Nothing is sent", str(wonder.exception))
        with mock.patch("expectrail.providers.chat_completion",
                        side_effect=AssertionError("a chat was sent")) as chat, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_LLM_PROVIDER": "ollama"}, clear=True):
            with self.assertRaises(BudgetStop):
                call_byo("what broke")
            spec, verdict, route = self._docs()
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(BudgetStop):
                    triage(spec=spec, verdict=verdict, route=route, out=Path(tmp) / "out")
                self.assertFalse((Path(tmp) / "out" / "triage.json").exists())
        chat.assert_not_called()

    def test_one_request_is_sent_and_the_next_stops_instead_of_falling_back(self):
        from agents.triage import call_byo, call_wonder, triage

        class Reply:
            def read(self):
                return b'{"choices":[{"message":{"content":"a bug"}}]}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        opened: list = []

        def urlopen(*_args, **_kwargs):
            opened.append(1)
            return Reply()

        with mock.patch("agents.triage.urllib.request.urlopen", side_effect=urlopen), \
                mock.patch.dict(os.environ, {"EXPECTRAIL_TRIAGE_USD_CAP": "0.05",
                                             "MODEL_API_KEY": "test-not-a-key"}, clear=True):
            self.assertEqual(call_wonder("what broke", "test-not-a-key"), "a bug")
            with self.assertRaises(BudgetStop) as stopped:
                call_wonder("again", "test-not-a-key")
            spec, verdict, route = self._docs()
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(BudgetStop) as via_triage:
                    triage(spec=spec, verdict=verdict, route=route, out=Path(tmp) / "out")
                report = Path(tmp) / "out" / "bug-report.md"
                self.assertFalse(report.exists() and "offline-fallback" in report.read_text())
        self.assertIn("was not sent", str(stopped.exception))
        self.assertIn("was not sent", str(via_triage.exception))
        self.assertEqual(opened, [1])

        reset_for_tests()
        answers = []

        def chat(*_args, **_kwargs):
            answers.append(1)
            return {"choices": [{"message": {"content": "byo bug"}}]}

        with mock.patch("expectrail.providers.chat_completion", side_effect=chat), \
                mock.patch.dict(os.environ, {"EXPECTRAIL_LLM_PROVIDER": "ollama",
                                             "EXPECTRAIL_TRIAGE_USD_CAP": "0.05"}, clear=True):
            text, source = call_byo("what broke")
            self.assertIn("ollama/", source)
            self.assertEqual(text, "byo bug")
            with self.assertRaises(BudgetStop) as byo_stopped:
                call_byo("again")
        self.assertIn("was not sent", str(byo_stopped.exception))
        self.assertEqual(answers, [1])


class VisionMonthTest(_SpendCase):
    def test_a_run_reserves_its_whole_cap_and_a_run_past_200_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "month.json"
            now = datetime(2026, 11, 14, tzinfo=timezone.utc)
            status = admit_vision_month(10, path=ledger, job_id="job-a", now=now)
            self.assertTrue(status["admitted"])
            self.assertEqual(read_vision_month(ledger)["spentUsd"], 10)
            again = admit_vision_month(10, path=ledger, job_id="job-a", now=now)
            self.assertEqual(again["spentUsd"], 10)
            self.assertEqual(len(read_vision_month(ledger)["entries"]), 1)

            reset_for_tests()
            full = {
                "format": "expectrail.vision-month/v1",
                "month": "2026-11",
                "limitUsd": 200,
                "spentUsd": 195,
                "entries": [{"jobId": "earlier", "reservedUsd": 195, "at": "2026-11-01T00:00:00+00:00"}],
            }
            ledger.write_text(json.dumps(full) + "\n", encoding="utf-8")
            before = ledger.read_bytes()
            with self.assertRaises(BudgetStop) as refused:
                admit_vision_month(6, path=ledger, job_id="job-b", now=now)
            self.assertIn("$200", str(refused.exception))
            self.assertIn("not started", str(refused.exception))
            self.assertEqual(ledger.read_bytes(), before)
            with self.assertRaises(BudgetStop):
                admit_vision_month(6, path=ledger, job_id="job-b", now=now)
            self.assertEqual(ledger.read_bytes(), before)

            reset_for_tests()
            rolled = admit_vision_month(4, path=ledger, job_id="job-c",
                                        now=datetime(2026, 12, 1, tzinfo=timezone.utc))
            self.assertEqual((rolled["spentUsd"], read_vision_month(ledger)["month"]), (4, "2026-12"))

    def test_two_processes_cannot_both_pass_the_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "month.json"
            code = (
                "import sys\n"
                "from pathlib import Path\n"
                "from expectrail.spend import BudgetStop, admit_vision_month\n"
                "try:\n"
                "    admit_vision_month(150, path=Path(sys.argv[1]), job_id=sys.argv[2])\n"
                "    print('ok')\n"
                "except BudgetStop:\n"
                "    print('stop')\n"
            )
            procs = [
                subprocess.Popen([sys.executable, "-c", code, str(ledger), name], cwd=REPO,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for name in ("one", "two")
            ]
            outs = []
            for proc in procs:
                out, err = proc.communicate(timeout=30)
                self.assertEqual(proc.returncode, 0, err)
                outs.append(out.strip())
            self.assertEqual(sorted(outs), ["ok", "stop"])
            self.assertEqual(read_vision_month(ledger)["spentUsd"], 150)

    def test_sam_refuses_before_it_sends_when_the_month_would_be_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "month.json"
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            full = {
                "format": "expectrail.vision-month/v1",
                "month": month,
                "limitUsd": 200,
                "spentUsd": 195,
                "entries": [{"jobId": "earlier", "reservedUsd": 195, "at": "2026-11-01T00:00:00+00:00"}],
            }
            ledger.write_text(json.dumps(full) + "\n", encoding="utf-8")
            before = ledger.read_bytes()
            env = {"EXPECTRAIL_SAM_USD_CAP": "6", LEDGER_ENV: str(ledger)}
            with mock.patch.dict(os.environ, env):
                with self.assertRaises(sam.SamError) as refused:
                    MetaSamClient(sleep=lambda _s: None)._call({"x": 1})
            self.assertEqual(refused.exception.kind, "budget")
            self.assertIn("$200", str(refused.exception))
            self.assertEqual((sam.sam_usage()["images"], sam.sam_usage()["reservedUsd"]), (0, 0.0))
            self.assertEqual(ledger.read_bytes(), before)
            # Unset ledger: the same stand-in sends, as it did before the month existed.
            sam._usage.update({"requests": 0, "images": 0, "videoFrames": 0, "reservedUsd": 0.0})
            with mock.patch.dict(os.environ, {"EXPECTRAIL_SAM_USD_CAP": "1"}):
                MetaSamClient(transport=lambda body: (b"{}", "application/json"),
                              sleep=lambda _s: None)._call({"x": 1})
            self.assertEqual(sam.sam_usage()["images"], 1)
            self.assertEqual(ledger.read_bytes(), before)

    def test_a_month_with_room_is_charged_once_for_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "month.json"
            sent: list = []

            def ok(body):
                sent.append(1)
                return b"{}", "application/json"

            env = {"EXPECTRAIL_SAM_USD_CAP": "1", LEDGER_ENV: str(ledger), "EXPECTRAIL_JOB_ID": "job-9"}
            with mock.patch.dict(os.environ, env):
                client = MetaSamClient(transport=ok, sleep=lambda _s: None)
                client._call({"x": 1})
                client._call({"x": 2})
            doc = read_vision_month(ledger)
            self.assertEqual(doc["spentUsd"], 1)
            self.assertEqual(len(doc["entries"]), 1)
            self.assertEqual(doc["entries"][0]["jobId"], "job-9")
            self.assertEqual(sent, [1, 1])
            self.assertAlmostEqual(sam.sam_usage()["reservedUsd"], 2 * sam.USD_PER_IMAGE)


class CliTest(_SpendCase):
    def test_month_check_and_job_budget_say_what_happened(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "month.json"
            admitted = subprocess.run(
                [sys.executable, "-m", "expectrail.spend", "month-check", "--cap", "10", "--ledger", str(ledger)],
                cwd=REPO, capture_output=True, text=True, check=False,
            )
            self.assertEqual(admitted.returncode, 0, admitted.stderr)
            self.assertIn("admitted", admitted.stdout)
            self.assertEqual(read_vision_month(ledger)["spentUsd"], 10)
            full = read_vision_month(ledger)
            full["spentUsd"] = 195
            full["entries"] = [{"jobId": "earlier", "reservedUsd": 195, "at": "2026-11-01T00:00:00+00:00"}]
            ledger.write_text(json.dumps(full) + "\n", encoding="utf-8")
            before = ledger.read_bytes()
            refused = subprocess.run(
                [sys.executable, "-m", "expectrail.spend", "month-check", "--cap", "6", "--ledger", str(ledger)],
                cwd=REPO, capture_output=True, text=True, check=False,
            )
            self.assertEqual(refused.returncode, 1)
            self.assertIn("$200", refused.stderr)
            self.assertEqual(ledger.read_bytes(), before)
            out = Path(tmp) / "budget.json"
            wrote = subprocess.run(
                [sys.executable, "-m", "expectrail.spend", "job-budget", "job-1", "--out", str(out)],
                cwd=REPO, capture_output=True, text=True, check=False,
            )
            self.assertEqual(wrote.returncode, 0, wrote.stderr)
            self.assertEqual(read_job_budget(out)["jobId"], "job-1")


if __name__ == "__main__":
    unittest.main()
