"""Unit and contract tests for Expectrail's BYO-LLM, BYO-Fixer, BYO-Vision, and MCP layers."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.byo_fixer import build_agent_cli_command, extract_unified_diff, resolve_fixer_agent
from agents.byo_vision import (
    BYOVLMObserverClient,
    normalize_box_to_pixels,
    png_dimensions,
    select_event_keyframes,
)
from agents.mcp_server import handle_jsonrpc_message
from expectrail.providers import (
    build_http_payload,
    chat_completion,
    detect_default_provider,
    resolve_provider,
    strip_json_fences,
)

# Minimal valid 1600x960 PNG header bytes for vision tests
FAKE_PNG_1600x960 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x06@\x00\x00\x03\xc0"
    b"\x08\x02\x00\x00\x00\x00\x00\x00\x00"
)


class TestBYOProviders(unittest.TestCase):
    def test_auto_detect_anthropic_and_openai(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=True):
            self.assertEqual(detect_default_provider(), "anthropic")
            cfg = resolve_provider(role="SPEC")
            self.assertEqual(cfg.provider, "anthropic")
            self.assertEqual(cfg.protocol, "anthropic")
            self.assertEqual(cfg.api_key, "sk-ant-test")

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-proj-test"}, clear=True):
            self.assertEqual(detect_default_provider(), "openai")
            cfg = resolve_provider(role="TRIAGE")
            self.assertEqual(cfg.provider, "openai")
            self.assertEqual(cfg.model, "gpt-4o")

    def test_ollama_requires_no_api_key(self) -> None:
        with patch.dict(os.environ, {"EXPECTRAIL_LLM_PROVIDER": "ollama"}, clear=True):
            cfg = resolve_provider(role="SPEC")
            self.assertEqual(cfg.provider, "ollama")
            self.assertEqual(cfg.api_base, "http://localhost:11434/v1")
            self.assertEqual(cfg.api_key, "local-no-key")

    def test_legacy_meta_fallback_preserved(self) -> None:
        with patch.dict(os.environ, {"MODEL_API_KEY": "meta-test-key"}, clear=True):
            cfg = resolve_provider(
                role="TRIAGE",
                legacy_default_model="muse-wonder-1.0",
                legacy_key_envs=("MODEL_API_KEY",),
            )
            self.assertEqual(cfg.provider, "meta")
            self.assertEqual(cfg.model, "muse-wonder-1.0")
            self.assertEqual(cfg.api_key, "meta-test-key")

    def test_anthropic_payload_and_image_translation(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-123"}, clear=True):
            cfg = resolve_provider(role="VLM")
            messages = [
                {"role": "system", "content": "Be strict."},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                        {"type": "text", "text": "Find the robot."},
                    ],
                },
            ]
            url, headers, payload = build_http_payload(cfg, messages, json_schema={"type": "object"})
            self.assertEqual(url, "https://api.anthropic.com/v1/messages")
            self.assertEqual(headers["x-api-key"], "sk-ant-123")
            self.assertIn("JSON Schema", payload["system"])
            user_blocks = payload["messages"][0]["content"]
            self.assertEqual(user_blocks[0]["type"], "image")
            self.assertEqual(user_blocks[0]["source"]["data"], "AAAA")
            self.assertEqual(user_blocks[1]["text"], "Find the robot.")

    def test_anthropic_is_never_sent_a_temperature(self) -> None:
        """The Messages API rejects it outright on current models:

            HTTP 400 invalid_request_error: `temperature` is deprecated for this model

        Every caller asks for 0.0 (agents/triage.py, agents/byo_fixer.py, agents/byo_vision.py,
        expectrail/spec_writer.py), so sending it failed every anthropic call, not one of them.
        """
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-123"}, clear=True):
            cfg = resolve_provider(role="TRIAGE")
            messages = [{"role": "user", "content": "why did it fall through?"}]
            for requested in (0.0, 0.7, None):
                _, _, payload = build_http_payload(cfg, messages, temperature=requested)
                self.assertNotIn("temperature", payload, f"temperature={requested!r} reached anthropic")
            # and the rest of the payload is still built
            self.assertEqual(payload["model"], cfg.model)
            self.assertEqual(payload["messages"], [{"role": "user", "content": "why did it fall through?"}])

    def test_an_openai_compatible_provider_still_gets_the_temperature(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-123"}, clear=True):
            cfg = resolve_provider(role="TRIAGE")
            _, _, payload = build_http_payload(cfg, [{"role": "user", "content": "hi"}], temperature=0.0)
            self.assertEqual(payload["temperature"], 0.0)
            _, _, payload = build_http_payload(cfg, [{"role": "user", "content": "hi"}], temperature=None)
            self.assertNotIn("temperature", payload)

    def test_chat_completion_normalizes_anthropic_response(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-123"}, clear=True):
            cfg = resolve_provider(role="SPEC")
            fake_transport = lambda u, h, p: {
                "model": "claude-3-7-sonnet-latest",
                "content": [{"type": "text", "text": '```json\n{"ok": true}\n```'}],
            }
            res = chat_completion(
                [{"role": "user", "content": "hi"}],
                config=cfg,
                transport=fake_transport,
            )
            content = strip_json_fences(res["choices"][0]["message"]["content"])
            self.assertEqual(json.loads(content), {"ok": True})


class TestBYOFixerAndVision(unittest.TestCase):
    def test_build_agent_cli_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wt = Path(tmp)
            cmd_claude = build_agent_cli_command("claude-code", "Fix player mask", wt, model="claude-3-7-sonnet")
            self.assertEqual(cmd_claude[0], "claude")
            self.assertIn("--allowedTools", cmd_claude)

            cmd_codex = build_agent_cli_command("codex", "Fix player mask", wt)
            self.assertEqual(cmd_codex[0], "codex")
            self.assertIn("full-auto", cmd_codex)

    def test_the_sandbox_record_describes_the_run_not_a_meta_gateway(self) -> None:
        """sandbox.json backs the README's isolation claim, so it must describe what ran.

        It used to read "host network (the key gateway speaks only to Meta's API)" for every bwrap
        run whatever the agent, beside a gateway recorded as off — a Claude Code run named a Meta
        constraint that was never applied (workflow run 42728501874).
        """
        import subprocess
        import tempfile
        from pathlib import Path

        from agents.byo_fixer import run_byo_agent

        done = subprocess.CompletedProcess(["claude"], 0, "", "")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-123", "PATH": "/usr/bin"}, clear=True), \
                patch("agents.sandbox.run_sandboxed", return_value=done), \
                patch("agents.sandbox.detect_sandbox", return_value="bwrap"), \
                patch("agents.sandbox.muse_kind_for", return_value="bwrap"):
            _, meta = run_byo_agent("fix it", Path(tmp), Path(tmp), agent="claude-code")

        self.assertEqual(meta["kind"], "bwrap")
        self.assertEqual(meta["agent"], "claude-code")
        self.assertEqual(meta["network"], "host network")  # stated plainly, never more isolation
        self.assertNotIn("Meta", meta["network"])
        self.assertEqual(meta["gateway"]["mode"], "off")  # agents/gateway.py reads this
        self.assertIn("Meta", meta["gateway"]["why"])  # the reason lives with the gateway
        # the provider key the agent actually received, by name only
        self.assertEqual(meta["keyEnvs"], ["ANTHROPIC_API_KEY"])
        self.assertNotIn("sk-ant-123", json.dumps(meta))

    def test_the_sandbox_record_names_no_key_the_agent_did_not_get(self) -> None:
        import subprocess
        import tempfile
        from pathlib import Path

        from agents.byo_fixer import run_byo_agent

        done = subprocess.CompletedProcess(["codex"], 0, "", "")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-123", "PATH": "/usr/bin"}, clear=True), \
                patch("agents.sandbox.run_sandboxed", return_value=done), \
                patch("agents.sandbox.detect_sandbox", return_value="bwrap"), \
                patch("agents.sandbox.muse_kind_for", return_value="bwrap"):
            _, meta = run_byo_agent("fix it", Path(tmp), Path(tmp), agent="codex")
        # codex takes OPENAI_API_KEY, which is not set, so it received no provider key
        self.assertEqual(meta["keyEnvs"], [])

    def test_extract_unified_diff(self) -> None:
        sample = (
            "Here is the fix:\n```diff\n--- a/player/player.tscn\n+++ b/player/player.tscn\n"
            "@@ -10,1 +10,1 @@\n-collision_mask = 14\n+collision_mask = 30\n```\n"
        )
        diff = extract_unified_diff(sample)
        self.assertTrue(diff.startswith("--- a/player/player.tscn"))
        self.assertIn("+collision_mask = 30", diff)

    def test_coordinate_normalization_and_out_of_frame_guard(self) -> None:
        px = normalize_box_to_pixels([500, 500, 600, 750], (1600, 960), coords="norm1000")
        self.assertEqual(px, [800.0, 480.0, 960.0, 720.0])

        with self.assertRaises(ValueError):
            # Box way outside image bounds (>2% tolerance) must be rejected, never clipped
            normalize_box_to_pixels([500, 500, 1400, 750], (1600, 960), coords="norm1000")

    def test_event_keyframe_sampling(self) -> None:
        trace = [
            {"frame": i, "on_floor": i >= 15, "vy": 10.0 if i < 15 else 0.0, "y": 500 + i * 2}
            for i in range(30)
        ]
        frames = select_event_keyframes(trace, 30, base_stride=10)
        # Frame 15 is where on_floor flips False -> True; frames 14, 15, 16 must be included
        self.assertIn(0, frames)
        self.assertIn(14, frames)
        self.assertIn(15, frames)
        self.assertIn(16, frames)
        self.assertIn(29, frames)
        self.assertLess(len(frames), 15)

    def test_mcp_server_initialize_and_tools_list(self) -> None:
        init_resp = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertIsNotNone(init_resp)
        self.assertEqual(init_resp["result"]["serverInfo"]["name"], "expectrail-mcp")

        list_resp = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tool_names = [t["name"] for t in list_resp["result"]["tools"]]
        self.assertIn("expectrail_draft_spec", tool_names)
        self.assertIn("expectrail_verify_build", tool_names)
        self.assertIn("expectrail_trust_check", tool_names)


if __name__ == "__main__":
    unittest.main()
