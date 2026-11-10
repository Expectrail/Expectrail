"""The BYO layer wired into Expectrail's entry points: the Meta path is unchanged, BYO is used only
when asked for, and the trust rules (key separation, a VLM alone never decides) still hold."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.orchestrator import build_repair_request
from expectrail.contracts import load, validate
from harness.run import REPO

FIX = REPO / "agents" / "fixtures" / "fix-collision-mask.patch"
FRAME = REPO / "agents" / "fixtures" / "frames" / "before-fall.png"


def _request():
    return build_repair_request(
        request_id="rr-byo",
        spec=load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
        verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
        route=load(REPO / "harness" / "routes" / "smoke.json", "route"),
        base_patch="bugs/physics-fall-through/v1.patch",
        key_frames=["frames/f00000008.png"],
    )


class ProviderSelectionTest(unittest.TestCase):
    def test_meta_key_keeps_the_legacy_path(self):
        from expectrail.providers import byo_requested, detect_default_provider

        env = {"MODEL_API_KEY": "meta", "ANTHROPIC_API_KEY": "sk-ant"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(detect_default_provider(), "meta")
            self.assertFalse(byo_requested("TRIAGE"))
            self.assertFalse(byo_requested("SPEC"))

    def test_explicit_provider_or_no_meta_key_selects_byo(self):
        from expectrail.providers import byo_requested

        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "m", "EXPECTRAIL_LLM_PROVIDER": "openai"}, clear=True):
            self.assertTrue(byo_requested("TRIAGE"))
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "m", "EXPECTRAIL_TRIAGE_PROVIDER": "meta"}, clear=True):
            self.assertFalse(byo_requested("TRIAGE"))
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant"}, clear=True):
            self.assertTrue(byo_requested("TRIAGE"))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(byo_requested("TRIAGE"))

    def test_unknown_provider_is_an_error_not_openai(self):
        from expectrail.providers import resolve_provider

        with mock.patch.dict(os.environ, {"EXPECTRAIL_LLM_PROVIDER": "openia"}, clear=True):
            with self.assertRaises(RuntimeError):
                resolve_provider("SPEC")


class ModeTest(unittest.TestCase):
    def test_auto_mode_counts_byo_triage_and_fixer(self):
        from agents.keys import resolve_mode

        with mock.patch.dict(os.environ, {"EXPECTRAIL_LLM_PROVIDER": "ollama",
                                          "EXPECTRAIL_FIXER_AGENT": "llm-patch"}, clear=True):
            mode = resolve_mode("auto")
        self.assertFalse(mode["offline_triage"])
        self.assertTrue(mode["use_muse"])

    def test_offline_mode_ignores_byo(self):
        from agents.keys import resolve_mode

        with mock.patch.dict(os.environ, {"EXPECTRAIL_LLM_PROVIDER": "ollama",
                                          "EXPECTRAIL_FIXER_AGENT": "llm-patch"}, clear=True):
            mode = resolve_mode("offline")
        self.assertTrue(mode["offline_triage"])
        self.assertFalse(mode["use_muse"])

    def test_installed_agent_never_replaces_muse_implicitly(self):
        from agents.keys import byo_fixer_agent, fixer_ready

        with mock.patch.dict(os.environ, {"META_API_KEY": "k"}, clear=True), \
                mock.patch("shutil.which", side_effect=lambda b: f"/usr/bin/{b}"):
            self.assertIsNone(byo_fixer_agent())
            self.assertTrue(fixer_ready())  # Muse, as before


class TriageTest(unittest.TestCase):
    def _run(self, out, **kwargs):
        from agents.triage import triage

        return triage(spec=load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
                      verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
                      route=load(REPO / "harness" / "routes" / "smoke.json", "route"), out=out, **kwargs)

    def test_meta_key_calls_wonder_not_byo(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"MODEL_API_KEY": "m", "ANTHROPIC_API_KEY": "a"}, clear=True), \
                mock.patch("agents.triage.call_wonder", return_value="wonder report") as wonder, \
                mock.patch("agents.triage.call_byo") as byo:
            self._run(Path(tmp))
            meta = json.loads((Path(tmp) / "triage.json").read_text())
        wonder.assert_called_once()
        byo.assert_not_called()
        self.assertEqual(meta, {"source": "muse-wonder-1.0", "model": "muse-wonder-1.0"})

    def test_byo_provider_triages(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_LLM_PROVIDER": "ollama"}, clear=True), \
                mock.patch("agents.triage.call_byo", return_value=("byo report", "ollama/qwen")), \
                mock.patch("agents.triage.call_wonder") as wonder:
            self._run(Path(tmp))
            meta = json.loads((Path(tmp) / "triage.json").read_text())
            report = (Path(tmp) / "bug-report.md").read_text()
        wonder.assert_not_called()
        self.assertEqual(meta["source"], "ollama/qwen")
        self.assertIn("byo report", report)

    def test_a_failed_byo_call_says_why_on_stdout_as_well_as_in_the_report(self):
        """The loop refuses a fallback either way; a CI log should not need the run's artifact to
        say whether the key, the model or the request was at fault."""
        import contextlib
        import io

        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_LLM_PROVIDER": "anthropic",
                                             "ANTHROPIC_API_KEY": "a"}, clear=True), \
                mock.patch("agents.triage.call_byo",
                           side_effect=RuntimeError("HTTP 400 from anthropic: `temperature` is deprecated")), \
                contextlib.redirect_stdout(buf):
            self._run(Path(tmp))
            meta = json.loads((Path(tmp) / "triage.json").read_text())
            report = (Path(tmp) / "bug-report.md").read_text()
        self.assertEqual(meta["source"], "offline-fallback")
        self.assertIn("temperature` is deprecated", report)
        printed = buf.getvalue()
        self.assertIn("::warning title=Triage fell back to the offline report::", printed)
        self.assertIn("temperature` is deprecated", printed)
        self.assertEqual(len(printed.strip().splitlines()), 1, printed)  # one line: annotations are per-line

    def test_a_provider_that_answers_with_nothing_is_a_failure_not_a_live_triage(self):
        """Every model failure becomes needs-review, never a pass. An empty answer is a failure:
        it used to be recorded as the model's own, with an empty bug report behind it."""
        import contextlib
        import io

        from expectrail.providers import ProviderConfig

        cfg = ProviderConfig(provider="anthropic", protocol="anthropic",
                             api_base="https://api.anthropic.com/v1",
                             model="claude-sonnet-5-5", api_key="sk-ant-1")
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_LLM_PROVIDER": "anthropic",
                                             "ANTHROPIC_API_KEY": "a"}, clear=True), \
                mock.patch("expectrail.providers.resolve_provider", return_value=cfg), \
                mock.patch("expectrail.providers.chat_completion", return_value={"choices": [
                    {"message": {"content": "   "}}]}), \
                contextlib.redirect_stdout(buf):
            self._run(Path(tmp))
            meta = json.loads((Path(tmp) / "triage.json").read_text())
        self.assertEqual(meta["source"], "offline-fallback")
        self.assertIn("answered with no text", buf.getvalue())

    def test_offline_stays_offline_with_byo_configured(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_LLM_PROVIDER": "ollama"}, clear=True), \
                mock.patch("agents.triage.call_byo") as byo:
            self._run(Path(tmp), offline=True)
            meta = json.loads((Path(tmp) / "triage.json").read_text())
        byo.assert_not_called()
        self.assertEqual(meta["source"], "offline")


class SpecWriterTest(unittest.TestCase):
    def test_provider_transport_drafts_a_valid_spec(self):
        from expectrail.spec_writer import draft, provider_transport

        answer = {"objects": {"player": {"prompt": "blue robot"}, "ground": {"prompt": "grass-topped ground"}},
                  "assertion": {"type": "never-crosses", "object": "player",
                                "boundary": {"relativeTo": "ground", "edge": "top", "side": "above",
                                             "tolerancePx": 8}}}
        seen = {}

        def fake_chat(messages, **kwargs):
            seen.update(kwargs)
            return {"choices": [{"message": {"content": json.dumps(answer)}}]}

        with mock.patch.dict(os.environ, {"EXPECTRAIL_LLM_PROVIDER": "ollama"}, clear=True), \
                mock.patch("expectrail.providers.chat_completion", side_effect=fake_chat):
            transport, cfg = provider_transport()
            spec, problems = draft("The player never falls through the ground", "p", cfg.model, transport=transport)
        self.assertEqual(problems, [])
        validate(spec, "test-spec")
        self.assertNotIn("approval", spec)
        self.assertFalse(seen["strict"])

    def test_cli_without_byo_uses_the_meta_transport(self):
        from expectrail import spec_writer

        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "m"}, clear=True), \
                mock.patch.object(spec_writer, "draft", return_value=(None, ["x"])) as d:
            spec_writer.main(["draft", "The player never falls"])
        self.assertIs(d.call_args.kwargs["transport"], spec_writer.http_transport)


class FixerTest(unittest.TestCase):
    def test_llm_patch_agent_produces_a_checked_candidate(self):
        from agents.fixer import run_fixer

        def fake_llm(prompt, work, out_patch, *, model=None):
            out_patch.write_text(FIX.read_text(), encoding="utf-8")
            return {"agent": "llm-patch", "provider": "ollama", "model": "qwen", "patch_path": str(out_patch),
                    "patch_bytes": 1}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("agents.byo_fixer.run_llm_patch_fixer", side_effect=fake_llm), \
                mock.patch("agents.fixer.run_muse_sandboxed") as muse:
            meta = run_fixer(_request(), Path(tmp) / "fix", candidate_patch=None, agent="llm-patch")
            patch = (Path(tmp) / "fix" / "candidate.patch").read_text()
        muse.assert_not_called()
        self.assertEqual(meta["source"], "llm-patch")
        self.assertTrue(meta["ok"])
        self.assertIn("+collision_mask = 30", patch)
        self.assertEqual(meta["sandbox"]["agent"], "llm-patch")

    def test_fixture_mode_ignores_the_agent(self):
        from agents.fixer import run_fixer

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_FIXER_AGENT": "claude-code"}, clear=True):
            meta = run_fixer(_request(), Path(tmp) / "fix", candidate_patch=FIX)
        self.assertEqual(meta["source"], "fixture")

    def test_cli_agent_runs_in_the_workspace_with_only_its_key(self):
        from agents.fixer import run_fixer

        seen = {}

        def fake_sandboxed(argv, *, work, env=None, network=True, kind=None, timeout=None, gateway=None,
                           extra_ro=None):
            seen.update(argv=argv, env=dict(env or {}), work=work, kind=kind)
            tscn = work / "player" / "player.tscn"
            tscn.write_text(tscn.read_text().replace("collision_mask = 14", "collision_mask = 30"))
            (work / "notes.txt").write_text("outside the editable globs")
            return mock.Mock(returncode=0, stdout="done", stderr="")

        env = {"ANTHROPIC_API_KEY": "fixer-key", "MODEL_API_KEY": "verifier-key", "META_API_KEY": "m",
               "PATH": os.environ.get("PATH", "")}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("agents.sandbox.run_sandboxed", side_effect=fake_sandboxed), \
                mock.patch("agents.fixer.detect_sandbox", return_value="none"):
            meta = run_fixer(_request(), Path(tmp) / "fix", candidate_patch=None, agent="claude-code")
            patch = (Path(tmp) / "fix" / "candidate.patch").read_text()
            leftover = (Path(tmp) / "fix" / "fixer-work" / ".expectrail-fixer-prompt.txt").exists()
        self.assertEqual(seen["argv"][0], "claude")
        self.assertEqual(seen["env"].get("ANTHROPIC_API_KEY"), "fixer-key")
        self.assertNotIn("MODEL_API_KEY", seen["env"])
        self.assertNotIn("META_API_KEY", seen["env"])
        self.assertEqual(meta["source"], "claude-code")
        self.assertIn("+collision_mask = 30", patch)
        self.assertNotIn("notes.txt", patch)
        self.assertFalse(leftover)

    def test_unknown_agent_is_refused(self):
        from agents.fixer import run_fixer

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_FIXER_AGENT": "cursor"}, clear=True):
            with self.assertRaises(SystemExit):
                run_fixer(_request(), Path(tmp) / "fix", candidate_patch=None)


class KeySeparationTest(unittest.TestCase):
    def test_fixer_and_vision_model_may_not_share_a_key(self):
        from agents.keys import require_separate_byo_keys

        env = {"EXPECTRAIL_FIXER_AGENT": "claude-code", "ANTHROPIC_API_KEY": "same",
               "EXPECTRAIL_VISION_BACKEND": "byo-vlm-engine", "EXPECTRAIL_VLM_PROVIDER": "anthropic"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit):
                require_separate_byo_keys()
        with mock.patch.dict(os.environ, {**env, "EXPECTRAIL_VLM_API_KEY": "its-own"}, clear=True):
            require_separate_byo_keys()  # same provider, different key: fine

    def test_fixer_may_not_hold_the_sam_key(self):
        from agents.keys import require_separate_byo_keys

        env = {"EXPECTRAIL_FIXER_AGENT": "codex", "OPENAI_API_KEY": "k", "MODEL_API_KEY": "k"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit):
                require_separate_byo_keys()


class VisionTest(unittest.TestCase):
    def test_a_vlm_alone_does_not_decide_a_verdict(self):
        from agents.sam_observations import SamError, default_client

        env = {"EXPECTRAIL_VISION_BACKEND": "byo-vlm", "EXPECTRAIL_VLM_PROVIDER": "ollama"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SamError):
                default_client(verdict=True)
            self.assertFalse(default_client(verdict=False).engine_checked)
        with mock.patch.dict(os.environ, {**env, "EXPECTRAIL_VISION_BACKEND": "byo-vlm-engine"}, clear=True):
            self.assertTrue(default_client(verdict=True).engine_checked)
        with mock.patch.dict(os.environ, {"EXPECTRAIL_VISION_BACKEND": "local-http"}, clear=True):
            self.assertEqual(default_client(verdict=True).model, "local-http-detector")

    def test_vision_failure_is_a_sam_error_and_no_score_is_guessed(self):
        from agents.byo_vision import LocalHTTPDetectorClient
        from agents.sam_observations import SamError

        client = LocalHTTPDetectorClient("http://127.0.0.1:9/detect")
        with self.assertRaises(SamError):
            client.segment(FRAME, "blue robot")  # nothing listening
        reply = mock.MagicMock()
        reply.__enter__.return_value.read.return_value = json.dumps({"objects": [{"box": [1, 1, 5, 5]}]}).encode()
        with mock.patch("urllib.request.urlopen", return_value=reply):
            with self.assertRaises(SamError):
                client.segment(FRAME, "blue robot")

    def test_keyframes_change_only_the_first_look(self):
        from agents.sam_observations import first_sample, sample

        indices = list(range(120))
        trace = {"rows": [{"frame": i, "onFloor": i >= 50, "player": [0, 600]} for i in range(120)]}
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(first_sample(indices, 4, trace), sample(indices, 4))
        with mock.patch.dict(os.environ, {"EXPECTRAIL_KEYFRAMES_ONLY": "1"}, clear=True):
            chosen = first_sample(indices, 4, trace)
            self.assertEqual(first_sample(indices, 1, trace), indices)  # every-frame specs stay every frame
            self.assertEqual(first_sample(indices, 4, None), sample(indices, 4))
        self.assertTrue({0, 49, 50, 51, 119} <= set(chosen))
        self.assertLess(len(chosen), len(sample(indices, 4)))


class McpTest(unittest.TestCase):
    def test_draft_spec_tool_writes_a_valid_unapproved_spec(self):
        from agents.mcp_server import handle_jsonrpc_message

        answer = {"objects": {"coin": {"prompt": "gold coin"}},
                  "assertion": {"type": "visible", "object": "coin", "minFraction": 0.9}}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_LLM_PROVIDER": "ollama"}, clear=True), \
                mock.patch("expectrail.providers.chat_completion",
                           return_value={"choices": [{"message": {"content": json.dumps(answer)}}]}):
            out = Path(tmp) / "coins.json"
            resp = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                           "params": {"name": "expectrail_draft_spec",
                                                      "arguments": {"instruction": "Coins are drawn",
                                                                    "out_path": str(out)}}})
            spec = json.loads(out.read_text())
        self.assertFalse(resp["result"]["isError"])
        validate(spec, "test-spec")
        self.assertNotIn("approval", spec)

    def test_bad_json_line_gets_a_parse_error(self):
        import io
        import sys

        from agents import mcp_server

        stdin, stdout = io.StringIO('not json\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n'), io.StringIO()
        with mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout):
            mcp_server.main()
        lines = [json.loads(x) for x in stdout.getvalue().splitlines()]
        self.assertEqual(lines[0]["error"]["code"], -32700)
        self.assertEqual(lines[1]["result"], {})


if __name__ == "__main__":
    unittest.main()
