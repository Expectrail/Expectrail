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

    def test_the_vision_provider_is_not_probed_as_a_text_model(self):
        """fireworks is Muse Glimmer, reached with frames through agents/byo_vision.py. A text chat
        completion to it says nothing about the path that uses it, and its default model id is
        overridden at the vision call site, so probing it here only produced a false 404."""
        self.assertNotIn("fireworks", byo_smoke.PROBED)

    def test_the_token_budget_cannot_truncate_a_one_word_answer(self):
        """At 16 a model that spends tokens before it speaks looks like a provider that said
        nothing, which is what the probe's first run reported for Spark Open and Muse Spark."""
        self.assertGreaterEqual(byo_smoke.MAX_TOKENS, 256)

    def test_the_probe_never_reads_the_verifiers_sam_key(self):
        """MODEL_API_KEY is the verifier's. agents/keys.py keeps it away from the fixer; the probe
        has no use for it either, so meta is probed with META_API_KEY alone."""
        for name in byo_smoke.PROBED:
            self.assertNotIn("MODEL_API_KEY", byo_smoke.key_envs(name), name)
        self.assertIn("META_API_KEY", byo_smoke.key_envs("meta"))


class WorkflowTest(unittest.TestCase):
    """The workflow and the probe must agree about which providers exist, and the job must hold no
    key for a provider it does not probe."""

    def setUp(self):
        import yaml

        from harness.run import REPO
        self.doc = yaml.safe_load((REPO / ".github" / "workflows" / "byo-smoke.yml").read_text())
        # YAML 1.1 reads a bare `on:` as the boolean True, so the triggers land under either key.
        self.triggers = self.doc.get("on") or self.doc[True]
        steps = self.doc["jobs"]["byo-smoke"]["steps"]
        self.env = next(s.get("env", {}) for s in steps if "byo_smoke" in str(s.get("run", "")) and s.get("env"))

    def test_the_dispatch_choices_are_the_probed_providers(self):
        options = self.triggers["workflow_dispatch"]["inputs"]["provider"]["options"]
        self.assertEqual([o for o in options if o], list(byo_smoke.PROBED))

    def test_the_job_holds_a_key_only_for_a_provider_it_probes(self):
        probed_envs = {e for name in byo_smoke.PROBED for e in byo_smoke.key_envs(name)}
        for name in self.env:
            if name.endswith("_API_KEY"):
                self.assertIn(name, probed_envs, f"{name} is set for a provider the probe does not call")

    def test_the_job_never_holds_the_verifiers_sam_key(self):
        self.assertNotIn("MODEL_API_KEY", self.env)

    def test_a_fork_pull_request_cannot_run_it(self):
        guard = self.doc["jobs"]["byo-smoke"]["if"]
        self.assertIn("head.repo.full_name == github.repository", guard)

    def test_the_key_bearing_job_runs_in_an_environment(self):
        """The approval gate for a pull request. The rules live in repository settings and the job
        cannot read them, so this only pins that the environment is still declared: removing the
        line would silently drop the gate."""
        self.assertEqual(self.doc["jobs"]["byo-smoke"]["environment"], "provider-keys")


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

    def test_an_answer_with_no_text_fails_and_says_why_it_stopped(self):
        """What the normalisation bug looked like: a 200 with nothing extractable from it. The stop
        reason is what separates that from a reply truncated before it said anything."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-1"}, clear=True):
            row = byo_smoke.probe(
                "anthropic",
                transport=lambda u, h, p: {"model": "m", "content": [], "stop_reason": "max_tokens"})
        self.assertEqual(row["result"], "fail")
        self.assertIn("no text", row["detail"])
        self.assertIn("stop_reason=max_tokens", row["detail"])

    def test_the_stop_reason_is_read_from_either_shape(self):
        self.assertEqual(byo_smoke.stop_reason({"choices": [{"finish_reason": "length"}]}),
                         "finish_reason=length")
        self.assertEqual(byo_smoke.stop_reason({"choices": [{}], "raw": {"stop_reason": "max_tokens"}}),
                         "stop_reason=max_tokens")
        self.assertEqual(byo_smoke.stop_reason({}), "no stop reason reported")

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
