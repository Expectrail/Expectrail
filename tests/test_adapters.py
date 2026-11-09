"""The engine-adapter boundary (harness/adapters.py): one run signature, the Godot digest unchanged."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import adapters
from harness import run as godot_harness
from harness.run import REPO


class TreeDigestTest(unittest.TestCase):
    def test_the_godot_digest_is_harness_run_s_on_the_real_game(self):
        game = REPO / "game" / "platformer"
        self.assertEqual(adapters.get("godot").tree_digest(), godot_harness.tree_digest(game))
        self.assertEqual(adapters.get("godot").tree_digest(game), godot_harness.tree_digest(game))

    def test_the_web_digest_is_harness_run_s_on_the_checkout_page(self):
        # agents/web_fix named the page with harness.run.tree_digest; the web adapter ignores nothing,
        # and the page has no .godot folder, so a repair request's base tree is the same either way.
        site = REPO / "apps" / "checkout" / "site"
        self.assertEqual(adapters.get("web").tree_digest(), godot_harness.tree_digest(site))

    def test_the_godot_ignore_list_matches_harness_run_with_nested_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "game"
            (root / "sub" / ".godot").mkdir(parents=True)
            (root / ".godot").mkdir()
            (root / "a.gd").write_text("extends Node\n")
            (root / "sub" / "b.tscn").write_text("[gd_scene]\n")
            (root / ".godot" / "cache.bin").write_bytes(b"\0\1")
            (root / "sub" / ".godot" / "other.bin").write_bytes(b"\2")
            (root / "sub" / "c").mkdir()
            (root / "sub" / "c" / ".godot").write_text("a file named .godot\n")
            self.assertEqual(adapters.tree_digest(root, (".godot",)), godot_harness.tree_digest(root))
            self.assertNotEqual(adapters.tree_digest(root, ()), godot_harness.tree_digest(root))

    def test_the_ignore_list_is_matched_below_the_root_only(self):
        # A Unity project checked out under a folder called Temp still hashes its own files.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Temp" / "project"
            (root / "Assets").mkdir(parents=True)
            (root / "Library").mkdir()
            (root / "Assets" / "Player.cs").write_text("class Player {}\n")
            (root / "Library" / "ArtifactDB").write_bytes(b"\0")
            with_library = adapters.tree_digest(root, ())
            digest = adapters.tree_digest(root, adapters.UNITY_IGNORE)
            (root / "Library" / "ArtifactDB").write_bytes(b"\1")
            self.assertEqual(adapters.tree_digest(root, adapters.UNITY_IGNORE), digest)
            self.assertNotEqual(adapters.tree_digest(root, ()), with_library)
            (root / "Assets" / "Player.cs").write_text("class Player { int hp; }\n")
            self.assertNotEqual(adapters.tree_digest(root, adapters.UNITY_IGNORE), digest)


class GodotWrapperTest(unittest.TestCase):
    def test_arguments_pass_through_to_harness_run(self):
        doc = {"format": "expectrail.replay/v0"}
        with mock.patch.object(godot_harness, "run", return_value=doc) as fake:
            got = adapters.get("godot").run(Path("r.json"), Path("out"), [Path("seed.patch"), Path("fix.patch")],
                                            game=Path("g"), fps=30, capture_frames=False)
        self.assertIs(got, doc)
        fake.assert_called_once_with(Path("r.json"), Path("out"), patches=[Path("seed.patch"), Path("fix.patch")],
                                     game=Path("g"), fps=30, capture_frames=False)

    def test_the_defaults_are_harness_run_s(self):
        with mock.patch.object(godot_harness, "run", return_value={}) as fake:
            adapters.get("godot").run("r.json", "out")
        fake.assert_called_once_with(Path("r.json"), Path("out"), patches=None, game=None, fps=60,
                                     capture_frames=True)

    def test_failures_are_passed_on_unchanged(self):
        godot = adapters.get("godot")
        for error in (SystemExit("godot failed (1); see out/godot.log"),
                      subprocess.CalledProcessError(1, ["godot", "--import"]), OSError("no display")):
            with self.subTest(error=type(error).__name__), mock.patch.object(godot_harness, "run", side_effect=error):
                with self.assertRaises(type(error)) as caught:
                    godot.run(Path("r.json"), Path("out"), [])
                self.assertIs(caught.exception, error)


class WebWrapperTest(unittest.TestCase):
    def test_arguments_pass_through_to_the_web_harness(self):
        from harness.web import run as web

        doc = {"format": "expectrail.web-replay/v0"}
        with mock.patch.object(web, "run", return_value=doc) as fake:
            got = adapters.get("web").run(Path("r.json"), Path("out"), [Path("bug.patch")], game=Path("site"))
        self.assertIs(got, doc)
        fake.assert_called_once_with(Path("r.json"), Path("out"), patches=[Path("bug.patch")], app=Path("site"))
        with mock.patch.object(web, "run", return_value=doc) as fake:
            adapters.get("web").run(Path("r.json"), Path("out"))
        fake.assert_called_once_with(Path("r.json"), Path("out"), patches=None, app=None)

    def test_a_web_harness_error_is_a_system_exit_with_the_cause_kept(self):
        from harness.web import run as web

        error = web.WebHarnessError("bug.patch does not apply")
        with mock.patch.object(web, "run", side_effect=error), self.assertRaises(SystemExit) as caught:
            adapters.get("web").run(Path("r.json"), Path("out"), [])
        self.assertEqual(str(caught.exception), "bug.patch does not apply")
        self.assertIs(caught.exception.__cause__, error)

    def test_options_the_web_harness_does_not_have_are_refused(self):
        with self.assertRaises(ValueError):
            adapters.get("web").run(Path("r.json"), Path("out"), fps=60)
        with self.assertRaises(ValueError):
            adapters.get("web").run(Path("r.json"), Path("out"), capture_frames=False)


class RegistryTest(unittest.TestCase):
    def test_godot_and_web_are_registered(self):
        self.assertEqual(adapters.names(), ("godot", "web"))
        self.assertIs(adapters.resolve("web"), adapters.get("web"))
        self.assertIs(adapters.resolve(adapters.GODOT), adapters.GODOT)
        with self.assertRaises(KeyError):
            adapters.get("unity")  # its data is ready (UNITY_IGNORE); it registers with its runner

    def test_a_taken_name_is_refused_unless_replaced(self):
        other = adapters.Adapter(**{**adapters.GODOT.__dict__, "prompt_subject": "something else"})
        with self.assertRaises(ValueError):
            adapters.register(other)
        self.assertIs(adapters.register(adapters.GODOT), adapters.GODOT)  # the same one again is fine
        try:
            adapters.register(other, replace=True)
            self.assertIs(adapters.get("godot"), other)
        finally:
            adapters.register(adapters.GODOT, replace=True)

    def test_what_each_adapter_says_about_its_engine(self):
        godot, web = adapters.get("godot"), adapters.get("web")
        self.assertEqual((godot.capture_fps, godot.ticks_per_second), (60, 120))
        self.assertEqual((web.capture_fps, web.ticks_per_second), (None, None))
        self.assertEqual(godot.log_name, "godot.log")
        self.assertIsNone(web.log_name)
        for adapter in (godot, web):
            self.assertTrue(adapter.game_root.is_dir(), adapter.name)
            self.assertTrue(adapter.default_route.is_file(), adapter.name)
            self.assertTrue(sorted(adapter.bugs.glob("*/v*.patch")), adapter.name)
        self.assertEqual(godot.trace_state({"player": [1, 2], "view": [0] * 6}), [1, 2])

    def test_frames_are_found_by_the_pattern_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = Path(tmp) / "frames"
            frames.mkdir()
            for n in (2, 0, 10, 1):
                (frames / f"f{n:08d}.png").write_bytes(b"")
            (frames / "notes.txt").write_text("")
            got = adapters.get("godot").frames(Path(tmp))
        self.assertEqual([p.name for p in got], ["f00000000.png", "f00000001.png", "f00000002.png", "f00000010.png"])


if __name__ == "__main__":
    unittest.main()
