"""#562: no model, only scripted provider responses and failed HTTP stand-ins."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from agents import byo_smoke
from expectrail import providers

ROOT = Path(__file__).resolve().parents[1]
LIMITED = {"choices": [{"finish_reason": "length", "message": {"content": None,
            "reasoning_content": "private reasoning must not appear in an error"}}],
           "usage": {"completion_tokens": 256, "completion_tokens_details": {"reasoning_tokens": 256}}}
OK = {"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}


def config(protocol="openai"):
    return providers.ProviderConfig("baseten" if protocol == "openai" else "anthropic", protocol,
                                    "https://inference.baseten.co/v1", "meta-models/muse-spark-open", "test-only")


class OutputLimitTest(unittest.TestCase):
    def test_sender_names_the_limit_separately_from_usage_and_never_retries(self):
        calls = []
        def sender(url, headers, payload):
            calls.append(payload)
            return copy.deepcopy(LIMITED)
        with self.assertRaisesRegex(RuntimeError, "output limit reached before any text") as caught:
            providers.chat_completion([], config=config(), max_tokens=2048, transport=sender)
        error = caught.exception
        self.assertEqual(error.code, "output-limit-before-text")
        self.assertEqual(error.limit, 2048)
        self.assertEqual(error.output_tokens, 256)
        self.assertEqual(error.reasoning_tokens, 256)
        self.assertIn("2048 tokens (requested limit), finish_reason=length", str(error))
        self.assertNotIn("private reasoning", str(error))
        self.assertEqual(len(calls), 1)

    def test_saved_responses_do_not_silently_extract_an_empty_string(self):
        for content in (None, "", " \n ", [{"type": "thinking", "text": "hidden"}]):
            with self.subTest(content=content):
                reply = copy.deepcopy(LIMITED)
                reply["choices"][0]["message"]["content"] = content
                with self.assertRaisesRegex(RuntimeError, "request limit not recorded"):
                    providers.extract_message_text(config(), reply)

    def test_anthropic_length_and_normalized_length_have_the_same_named_result(self):
        reply = {"content": [{"type": "thinking", "thinking": "hidden"}], "stop_reason": "max_tokens",
                 "usage": {"input_tokens": 8, "output_tokens": 128}}
        with self.assertRaisesRegex(RuntimeError, "128 tokens.*stop_reason=max_tokens") as caught:
            providers.chat_completion([], config=config("anthropic"), max_tokens=128,
                                      transport=lambda *args: reply)
        self.assertEqual(caught.exception.output_tokens, 128)
        normalized = {"choices": [{"message": {"content": ""}}], "raw": reply}
        with self.assertRaisesRegex(RuntimeError, "stop_reason=max_tokens"):
            providers.extract_message_text(config("anthropic"), normalized)

    def test_usage_is_never_inferred_from_the_request_limit(self):
        reply = {"choices": [{"finish_reason": "length", "message": {"content": ""}}]}
        with self.assertRaises(RuntimeError) as caught:
            providers.chat_completion([], config=config(), max_tokens=333, transport=lambda *a: reply)
        self.assertIsNone(caught.exception.output_tokens)
        self.assertIsNone(caught.exception.reasoning_tokens)
        self.assertIn("333 tokens (requested limit)", str(caught.exception))

    def test_nonempty_partial_text_keeps_its_previous_behavior(self):
        reply = copy.deepcopy(LIMITED)
        reply["choices"][0]["message"]["content"] = "some text"
        raw = providers.chat_completion([], config=config(), transport=lambda *a: reply)
        self.assertEqual(providers.extract_message_text(config(), raw), "some text")

    def test_empty_refusal_and_http_error_are_not_output_limit_results(self):
        refusal = {"choices": [{"finish_reason": "stop", "message": {"content": None, "refusal": "no"}}]}
        with patch.dict(os.environ, {"BASETEN_API_KEY": "test-only"}, clear=True):
            row = byo_smoke.probe("baseten", transport=lambda *a: refusal)
            self.assertEqual(row["result"], "fail")
            self.assertIn("finish_reason=stop", row["detail"])
            row = byo_smoke.probe("baseten", transport=Mock(side_effect=RuntimeError("HTTP 503")))
            self.assertEqual(row["result"], "fail")
            self.assertIn("HTTP 503", row["detail"])

    def test_fixer_accounts_for_the_reply_before_the_limit_error(self):
        invocation = Mock()
        invocation.lock = threading.RLock()
        with self.assertRaisesRegex(RuntimeError, "output limit reached"):
            providers.chat_completion([], role="FIXER", config=config(), invocation=invocation,
                                      transport=lambda *a: copy.deepcopy(LIMITED))
        invocation.reserve_request.assert_called_once()
        invocation.observe_request.assert_called_once()

    def test_a_fixer_reading_a_saved_reply_never_writes_a_candidate(self):
        from agents.byo_fixer import run_llm_patch_fixer
        invocation = Mock()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"BASETEN_API_KEY": "test-only", "EXPECTRAIL_MUSE_USD_CAP": "1"}, clear=True), \
                patch("expectrail.fixer_budget.start", return_value=invocation), \
                patch("agents.byo_fixer._collect_candidate_files", return_value="stand-in source"), \
                patch("agents.byo_fixer.chat_completion", return_value=copy.deepcopy(LIMITED)):
            candidate = Path(tmp) / "candidate.patch"
            with self.assertRaisesRegex(RuntimeError, "output limit reached"):
                run_llm_patch_fixer("fix", Path(tmp), candidate)
            self.assertFalse(candidate.exists())
            invocation.finish.assert_called_once()

    def test_spec_drafting_names_truncation_instead_of_json_or_none_errors(self):
        from expectrail.spec_writer import SpecDraftError, _parse
        with self.assertRaisesRegex(SpecDraftError, "output limit reached before any text"):
            _parse(copy.deepcopy(LIMITED))

    def test_legacy_triage_does_not_return_silent_empty_text(self):
        from agents.triage import call_wonder
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps(LIMITED).encode()
        with patch("expectrail.spend.hold"), patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "output limit reached"):
                call_wonder("why", "test-only")

    def test_legacy_triage_reports_the_named_failure_as_a_fallback(self):
        from agents.triage import triage
        with tempfile.TemporaryDirectory() as tmp, \
                patch("agents.triage.wonder_key", return_value="test-only"), \
                patch("agents.triage.call_wonder", side_effect=providers.OutputLimitReached("finish_reason=length", limit=256)), \
                patch("agents.triage.build_repair_request", return_value={}), \
                contextlib.redirect_stdout(io.StringIO()):
            triage(spec={"id":"example"}, verdict={}, route={}, out=Path(tmp), provider="meta")
            meta = json.loads((Path(tmp) / "triage.json").read_text())
            self.assertEqual(meta["source"], "offline-fallback")
            self.assertIn("output limit reached before any text", (Path(tmp) / "bug-report.md").read_text())


class SmokeAllowanceTest(unittest.TestCase):
    def test_baseten_uses_the_recorded_input_output_and_single_attempt_bounds(self):
        calls = []
        def sender(url, headers, payload):
            calls.append(payload)
            return copy.deepcopy(LIMITED)
        with patch.dict(os.environ, {"BASETEN_API_KEY": "test-only"}, clear=True):
            row = byo_smoke.probe("baseten", transport=sender)
        self.assertEqual(row["result"], "output-limit")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["max_tokens"], 2048)
        self.assertEqual(calls[0]["truncate_prompt_tokens"], 256)
        self.assertNotIn("reasoning_effort", calls[0])  # this model has no supported off switch
        self.assertNotIn("test-only", json.dumps(row))
        self.assertIn("2048 tokens", row["detail"])
        self.assertIn("finish_reason=length", row["detail"])

    def test_a_named_limit_result_fails_the_cli_and_is_counted_as_failed(self):
        row = {"provider": "baseten", "model": "m", "result": "output-limit", "detail": "output limit reached before any text"}
        out = io.StringIO()
        with patch("agents.byo_smoke.probe", return_value=row), contextlib.redirect_stdout(out):
            self.assertEqual(byo_smoke.main(["--provider", "baseten"]), 1)
        self.assertIn("0 answered, 1 failed", out.getvalue())
        self.assertIn("1 output-limit", out.getvalue())

    def test_recorded_tariff_and_budget_are_read_and_round_trip(self):
        from expectrail.spend import read_provider_capability, write_provider_capability
        record = read_provider_capability(ROOT / "contracts/examples/provider-capabilities/baseten.json")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capability.json"
            write_provider_capability(record, path)
            self.assertEqual(read_provider_capability(path), record)
        plan = byo_smoke.smoke_policy()
        self.assertEqual(plan, record["textSmoke"])
        self.assertEqual(byo_smoke.smoke_cost_nano_usd(plan), 9024000)
        self.assertEqual(plan["maxAttempts"], 1)

    def test_list_stays_offline_and_states_the_cost_before_a_key_is_present(self):
        out = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch("urllib.request.urlopen", side_effect=AssertionError("no network")), \
                contextlib.redirect_stdout(out):
            self.assertEqual(byo_smoke.main(["--list", "--provider", "baseten"]), 0)
        self.assertIn("$0.009024", out.getvalue())
        self.assertIn("2048 output tokens", out.getvalue())
        self.assertIn("skipped (no key)", out.getvalue())

    def test_other_providers_keep_256_tokens_without_input_truncation(self):
        calls = []
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}, clear=True):
            result = byo_smoke.probe("openai", transport=lambda u,h,p: calls.append(p) or OK)
        self.assertEqual(result["result"], "ok")
        self.assertEqual(calls[0]["max_tokens"], 256)
        self.assertNotIn("truncate_prompt_tokens", calls[0])

    def test_unknown_model_or_endpoint_cannot_use_the_recorded_tariff(self):
        for setting in ({"EXPECTRAIL_LLM_MODEL": "unknown"}, {"EXPECTRAIL_LLM_API_BASE": "https://example.invalid/v1"}):
            with self.subTest(setting=setting):
                sender = Mock(side_effect=AssertionError("must not send"))
                with patch.dict(os.environ, {"BASETEN_API_KEY": "test-only", **setting}, clear=True):
                    row = byo_smoke.probe("baseten", transport=sender)
                self.assertEqual(row["result"], "fail")
                self.assertIn("no recorded smoke allowance", row["detail"])
                sender.assert_not_called()

    def test_http_failure_gets_one_smoke_attempt_instead_of_hidden_retries(self):
        with patch.dict(os.environ, {"BASETEN_API_KEY": "test-only"}, clear=True), \
                patch("urllib.request.urlopen", side_effect=HTTPError("https://example.invalid",503,"unavailable",{},io.BytesIO(b"busy"))) as send, \
                patch("expectrail.providers.time.sleep") as sleep:
            row = byo_smoke.probe("baseten")
        self.assertEqual(row["result"], "fail")
        self.assertEqual(send.call_count, 1)
        sleep.assert_not_called()

    def test_duplicate_cli_provider_names_cannot_multiply_the_per_run_allowance(self):
        with patch("agents.byo_smoke.probe", return_value={"provider": "baseten", "model": "m", "result": "ok", "detail": "answered"}) as probe, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(byo_smoke.main(["--provider", "baseten", "baseten"]), 0)
        probe.assert_called_once_with("baseten")

    def test_invalid_capability_allowances_refuse_before_sending(self):
        original = json.loads((ROOT / "contracts/examples/provider-capabilities/baseten.json").read_text())
        for field, value in (("maxInputTokens", 0), ("maxOutputTokens", True), ("maxAttempts", 2), ("inputNanoUsdPerToken", 0)):
            with self.subTest(field=field):
                doc = copy.deepcopy(original)
                doc["textSmoke"][field] = value
                sender = Mock(side_effect=AssertionError("must not send"))
                with patch.dict(os.environ, {"BASETEN_API_KEY": "test-only"}, clear=True), \
                        patch("expectrail.gate.record.read_json", return_value=doc):
                    row = byo_smoke.probe("baseten", transport=sender)
                self.assertEqual(row["result"], "fail")
                sender.assert_not_called()

    def test_default_sender_still_has_three_attempts(self):
        def fail(*a, **k):
            raise HTTPError("https://example.invalid",503,"unavailable",{},io.BytesIO(b"busy"))
        with patch("urllib.request.urlopen", side_effect=fail) as send, patch("expectrail.providers.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                providers.chat_completion([], config=config())
        self.assertEqual(send.call_count, 3)

    def test_new_runtime_path_needs_neither_numpy_pillow_nor_jsonschema(self):
        code = "import sys; sys.path.insert(0, sys.argv[1]); sys.modules.update(numpy=None,PIL=None,jsonschema=None); from agents.byo_smoke import smoke_policy, smoke_cost_nano_usd; assert smoke_cost_nano_usd(smoke_policy()) == 9024000"
        result = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
