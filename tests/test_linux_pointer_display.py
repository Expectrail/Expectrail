"""Display selection through the Godot replay entry point, with a stand-in engine."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import run as harness


class LinuxPointerDisplayTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.route = self.root / "route.json"
        self.out = self.root / "out"
        self.engine = self.root / "godot"
        self.game = harness.REPO / "tests/projects/pointer-menu"
        self.programs = {"xvfb-run", "Xvfb", "xauth"}
        self.desktop = {"DISPLAY": ":42", "WAYLAND_DISPLAY": "wayland-1", "XDG_RUNTIME_DIR": "/run/user/1000"}
        self.enterContext(mock.patch.dict(os.environ, self.desktop, clear=True))
        self.enterContext(mock.patch.object(harness.sys, "platform", "linux"))
        self.enterContext(mock.patch.object(harness.shutil, "which", side_effect=lambda p: p if p in self.programs else None))
        self.enterContext(mock.patch.object(harness.box, "probe", return_value=(None, "bubblewrap unavailable")))
        self.cache = self.enterContext(mock.patch.object(harness, "ensure_import_cache", return_value=None))
        self.enterContext(mock.patch.object(harness, "godot_import"))
        self.capture = self.enterContext(mock.patch.object(harness.subprocess, "run", side_effect=self.record))

    def record(self, command, **kwargs):
        (self.out / "trace.json").write_text("{}")
        return subprocess.CompletedProcess(command, 0, "", "")

    def replay(self, *, pointer=True, capture_frames=True):
        events = [{"tick": 0, "action": "jump", "pressed": True}]
        if pointer:
            events.append({"tick": 1, "pointer": {"position": [100, 60]}})
        self.route.write_text(json.dumps({"format": "expectrail.route/v0", "name": "test",
                                          "seed": 1, "ticks": 3, "events": events}))
        harness.run(self.route, self.out, game=self.game, godot=self.engine,
                    capture_frames=capture_frames, sandbox="auto")
        return self.capture.call_args.args[0], self.capture.call_args.kwargs["env"]

    def test_rendered_mixed_route_uses_private_x11_on_x11_and_wayland_desktops(self):
        for display in (":42", ""):
            with self.subTest(display=display), mock.patch.dict(os.environ, DISPLAY=display):
                command, env = self.replay()
                self.assertEqual(command[0], "xvfb-run")
                self.assertEqual(command[command.index("--display-driver") + 1], "x11")
                self.assertNotIn("WAYLAND_DISPLAY", env)
                self.assertNotIn("XDG_RUNTIME_DIR", env)

    def test_missing_display_component_refuses_before_import_with_install_step(self):
        for program, package in (("xvfb-run", "xvfb"), ("Xvfb", "xvfb"), ("xauth", "xauth")):
            with self.subTest(program=program):
                self.programs.remove(program)
                with self.assertRaisesRegex(SystemExit, f"{program}.*install {package}"):
                    self.replay()
                self.cache.assert_not_called()
                self.capture.assert_not_called()
                self.programs.add(program)

    def test_action_only_and_headless_can_run_without_xvfb(self):
        self.programs.clear()
        command, env = self.replay(pointer=False)
        self.assertEqual(command[0], str(self.engine))
        self.assertEqual(env["DISPLAY"], self.desktop["DISPLAY"])
        command, _ = self.replay(capture_frames=False)
        self.assertEqual(command[:2], [str(self.engine), "--headless"])

    def test_macos_rendered_pointer_uses_native_display(self):
        self.programs.clear()
        with mock.patch.object(harness.sys, "platform", "darwin"):
            command, _ = self.replay()
        self.assertEqual(command[0], str(self.engine))
        self.assertNotIn("--display-driver", command)
