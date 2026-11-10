"""agents/byo_smoke.py: one live call per configured provider, and what it does without a key.

The probe exists because the provider tests use recorded responses. Its own tests therefore avoid
asserting anything a recorded response could fake: they check the decisions the probe makes about a
provider's answer, not the answer.
"""
import os
import unittest
from unittest.mock import patch

from agents import byo_smoke
from expectrail.providers import PROVIDER_DEFAULTS

ANTHROPIC_REPLY = {"model": "claude-sonnet-5-5", "content": [{"type": "text", "text": "ok"}]}
OPENAI_REPLY = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}


class ProbedProvidersTest(unittest.TestCase):
    def test_every_probed_provider_is_a_real_provider_that_needs_a_key(self):
        for name in byo_smoke.PROBED:
            self.assertIn(name, PROVIDER_DEFAULTS, name)
            self.assertTrue(PROVIDER_DEFAULTS[name]["requires_key"],
                            f"{name} needs no key, so a probe failure would say nothing")

    def test_the_local_server_providers_are_not_probed(self):
        """ollama and vllm default to localhost: there is nothing for CI to reach."""
        for name in ("ollama", "vllm"):
            self.assertNotIn(name, byo_smoke.PROBED)

    def test_the_probe_never_reads_the_verifiers_sam_key(self):
        """MODEL_API_KEY is the verifier's. agents/keys.py keeps it away from the fixer; the probe
        has no use for it either, so meta is probed with META_API_KEY alone."""
        for name in byo_smoke.PROBED:
            self.assertNotIn("MODEL_API_KEY", byo_smoke.key_envs(name), name)
        self.assertIn("META_API_KEY", byo_smoke.key_envs("meta"))


class ProbeTest(unittest.TestCase):
    def test_a_provider_with_no_key_is_skipped_not_failed(self):
        with patch.dict(os.environ, {}, clear=True):
            row = byo_smoke.probe("anthropic")
        self.assertEqual(row["result"], "skipped")
        self.assertIn("ANTHROPIC_API_KEY", row["detail"])

    def test_a_provider_that_answers_passes(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-1"}, clear=True):
            row = byo_smoke.probe("anthropic", transport=lambda u, h, p: ANTHROPIC_REPLY)
        self.assertEqual(row["result"], "ok")
        self.assertEqual(row["model"], "claude-sonnet-5-5")

    def test_an_openai_compatible_provider_that_answers_passes(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-1"}, clear=True):
            row = byo_smoke.probe("openai", transport=lambda u, h, p: OPENAI_REPLY)
        self.assertEqual(row["result"], "ok")

    def test_an_http_failure_is_a_result_not_a_crash(self):
        def boom(u, h, p):
            raise RuntimeError("HTTP 400 from anthropic: `temperature` is deprecated for this model")

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-1"}, clear=True):
            row = byo_smoke.probe("anthropic", transport=boom)
        self.assertEqual(row["result"], "fail")
        self.assertIn("temperature", row["detail"])

    def test_an_answer_with_no_text_fails(self):
        """What the normalisation bug looked like: a 200 with nothing extractable from it."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-1"}, clear=True):
            row = byo_smoke.probe("anthropic", transport=lambda u, h, p: {"model": "m", "content": []})
        self.assertEqual(row["result"], "fail")
        self.assertIn("no text", row["detail"])

    def test_the_reply_text_is_never_judged(self):
        """A model's wording must not be able to fail CI: any non-empty answer passes."""
        reply = {"model": "m", "content": [{"type": "text", "text": "I cannot help with that."}]}
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-1"}, clear=True):
            row = byo_smoke.probe("anthropic", transport=lambda u, h, p: reply)
        self.assertEqual(row["result"], "ok")


class AnnotationsAndExitTest(unittest.TestCase):
    def test_lines_annotate_each_provider_and_summarise(self):
        rows = [
            {"provider": "anthropic", "model": "m1", "result": "ok", "detail": "answered 2 characters"},
            {"provider": "openai", "model": "m2", "result": "fail", "detail": "HTTP 401"},
            {"provider": "meta", "model": None, "result": "skipped", "detail": "no key: set one of META_API_KEY"},
        ]
        out = byo_smoke.lines(rows)
        self.assertTrue(out[0].startswith("::notice title=BYO smoke anthropic::"))
        self.assertTrue(out[1].startswith("::error title=BYO smoke openai::"))
        self.assertIn("HTTP 401", out[1])
        self.assertTrue(out[2].startswith("::notice title=BYO smoke meta skipped::"))
        self.assertIn("1 answered, 1 failed, 1 skipped (no key)", out[3])

    def test_no_keys_anywhere_is_a_clean_pass(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(byo_smoke.main([]), 0)

    def test_one_failing_provider_fails_the_job(self):
        failed = {"provider": "anthropic", "model": "m", "result": "fail", "detail": "HTTP 400"}
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-1"}, clear=True), \
                patch("agents.byo_smoke.probe", return_value=failed):
            self.assertEqual(byo_smoke.main(["--provider", "anthropic"]), 1)

    def test_a_skip_alone_does_not_fail_the_job(self):
        skipped = {"provider": "anthropic", "model": None, "result": "skipped", "detail": "no key"}
        with patch.dict(os.environ, {}, clear=True), \
                patch("agents.byo_smoke.probe", return_value=skipped):
            self.assertEqual(byo_smoke.main(["--provider", "anthropic"]), 0)

    def test_list_makes_no_calls(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-1"}, clear=True), \
                patch("agents.byo_smoke.probe",
                      side_effect=AssertionError("--list must not call a provider")) as called:
            self.assertEqual(byo_smoke.main(["--list"]), 0)
        called.assert_not_called()


if __name__ == "__main__":
    unittest.main()
