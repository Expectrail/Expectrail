"""A project config's viewport and tick rate must agree with the game's project.godot (#657).

No engine is started. A config that disagrees with its game is refused before any replay, and the
message names the field and both values. A setting that cannot be read is refused too; nothing
falls back to a default for a value that is present but unreadable.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail import onboarding
from expectrail.godot_project import (
    DEFAULT_TICKS, DEFAULT_VIEWPORT, SettingsMismatch, declared_settings, require_declared_settings,
)
from expectrail.project_config import FILENAME, load, read_game
from harness import run as hr
from harness import sandbox as box

REPO = Path(__file__).resolve().parent.parent
CRATE = REPO / "tests" / "projects" / "crate-run" / "project"
LANE = REPO / "tests" / "projects" / "config-lane"
EXAMPLE = REPO / "contracts" / "examples" / "project.json"
FAKE = box.Tool("/usr/bin/bwrap", "0.9.0")

GODOT = """config_version=5
[application]
run/main_scene="res://main.tscn"
[display]
window/size/viewport_width=800
window/size/viewport_height=480
[physics]
common/physics_ticks_per_second=120
"""


def _game(root: Path, godot: str = GODOT) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.godot").write_text(godot, encoding="utf-8")
    return root


def _config(viewport=(800, 480), ticks=120, adapter="godot") -> dict:
    return {"adapter": adapter, "viewport": list(viewport), "physicsTicksPerSecond": ticks}


class DeclaredSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-settings-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_game_declares_its_viewport_and_rate(self):
        self.assertEqual(declared_settings(_game(self.tmp)), ([800, 480], 120))

    def test_unset_settings_are_godots_defaults(self):
        game = _game(self.tmp, "config_version=5\n[application]\nrun/main_scene=\"res://m.tscn\"\n")
        self.assertEqual(declared_settings(game), (list(DEFAULT_VIEWPORT), DEFAULT_TICKS))
        self.assertEqual(DEFAULT_VIEWPORT, (1152, 648))
        self.assertEqual(DEFAULT_TICKS, 60)
        require_declared_settings(game, _config((1152, 648), 60))

    def test_a_matching_config_is_accepted(self):
        require_declared_settings(_game(self.tmp), _config())

    def test_no_config_checks_nothing(self):
        require_declared_settings(_game(self.tmp, "not even godot"), None)

    def test_a_wrong_viewport_is_refused_and_names_the_field_and_both_values(self):
        with self.assertRaises(SettingsMismatch) as caught:
            require_declared_settings(_game(self.tmp), _config((640, 360)))
        message = str(caught.exception)
        for part in ("viewport", "[640, 360]", "[800, 480]", "display/window/size/viewport_width",
                     "No game was started"):
            self.assertIn(part, message)

    def test_one_axis_off_is_refused(self):
        with self.assertRaises(SettingsMismatch) as caught:
            require_declared_settings(_game(self.tmp), _config((800, 481)))
        self.assertIn("[800, 481]", str(caught.exception))

    def test_a_wrong_tick_rate_is_refused_and_names_the_field_and_both_values(self):
        with self.assertRaises(SettingsMismatch) as caught:
            require_declared_settings(_game(self.tmp), _config(ticks=60))
        message = str(caught.exception)
        for part in ("physicsTicksPerSecond", "60", "120", "physics/common/physics_ticks_per_second"):
            self.assertIn(part, message)

    def test_both_wrong_names_both_fields(self):
        with self.assertRaises(SettingsMismatch) as caught:
            require_declared_settings(_game(self.tmp), _config((640, 360), 60))
        self.assertIn("viewport", str(caught.exception))
        self.assertIn("physicsTicksPerSecond", str(caught.exception))

    def test_a_default_that_the_config_contradicts_is_refused(self):
        game = _game(self.tmp, "config_version=5\n[display]\nwindow/size/viewport_width=800\n")
        with self.assertRaises(SettingsMismatch) as caught:
            require_declared_settings(game, _config((800, 480), 60))
        self.assertIn("[800, 648]", str(caught.exception))

    def test_an_unreadable_value_is_refused_not_defaulted(self):
        for bad in ("800.5", "\"800\"", "abc", "-800", "0", ""):
            with self.subTest(bad=bad):
                game = _game(self.tmp / bad.replace('"', "q").replace(".", "d").replace("-", "m") / "g",
                             GODOT.replace("viewport_width=800", f"viewport_width={bad}"))
                with self.assertRaises(SettingsMismatch) as caught:
                    require_declared_settings(game, _config())
                self.assertIn("display/window/size/viewport_width", str(caught.exception))
        game = _game(self.tmp / "rate", GODOT.replace("ticks_per_second=120", "ticks_per_second=1001"))
        with self.assertRaises(SettingsMismatch) as caught:
            require_declared_settings(game, _config())
        self.assertIn("physics/common/physics_ticks_per_second", str(caught.exception))

    def test_a_setting_given_twice_is_refused(self):
        game = _game(self.tmp, GODOT + "[display]\nwindow/size/viewport_width=640\n")
        with self.assertRaises(SettingsMismatch) as caught:
            require_declared_settings(game, _config())
        self.assertIn("more than once", str(caught.exception))

    def test_a_feature_override_or_another_section_is_not_the_setting(self):
        # `.mobile` overrides apply on other platforms only; the same key in another section is
        # another setting. Neither replaces the base value the replay runs with.
        game = _game(self.tmp, GODOT + "window/size/viewport_width.mobile=640\n"
                     "[rendering]\nwindow/size/viewport_width=1\n")
        self.assertEqual(declared_settings(game), ([800, 480], 120))

    def test_a_missing_project_file_is_refused(self):
        self.tmp.mkdir(exist_ok=True)
        with self.assertRaises(SettingsMismatch):
            require_declared_settings(self.tmp, _config())

    def test_a_unity_config_is_not_compared_with_a_godot_file(self):
        require_declared_settings(_game(self.tmp, "not godot"), _config((1, 1), 1, adapter="unity"))

    def test_inspect_reads_the_same_settings(self):
        for game in (CRATE, LANE):
            with self.subTest(game=game.name):
                report = onboarding.inspect(game)
                self.assertEqual((report["viewport"], report["physicsTicksPerSecond"]), declared_settings(game))


class CheckedInConfigsTest(unittest.TestCase):
    def test_every_checked_in_config_with_its_game_agrees(self):
        for game in (CRATE, LANE):
            with self.subTest(game=game.relative_to(REPO).as_posix()):
                config = read_game(game)
                self.assertIsNotNone(config)
                require_declared_settings(game, config)
        # The contract's example is the crate's config (test_project_config holds them equal).
        require_declared_settings(CRATE, load(EXAMPLE, CRATE))


class ReplayRefusesTest(unittest.TestCase):
    """The replay stops before the import or any game run, on the game and on the copy."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="expectrail-settings-run-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"EXPECTRAIL_GODOT_CACHE": str(self.tmp / "cache")})
        env.start()
        self.addCleanup(env.stop)
        self.route = self.tmp / "route.json"
        self.route.write_text(json.dumps({"format": "expectrail.route/v0", "name": "t", "seed": 1,
                                          "ticks": 1, "events": []}), encoding="utf-8")
        self.godot = self.tmp / "godot"
        self.godot.write_bytes(b"not an engine")
        self.calls = []

    def engine(self, tool, argv, *, timeout, game, out, inputs=None, engine=None, env=None):
        self.calls.append(list(argv))
        (Path(game) / ".godot" / "imported").mkdir(parents=True, exist_ok=True)
        if "--import" not in argv:
            (Path(out) / "trace.json").write_text('{"physicsTicksPerSecond": 60, "rows": []}', encoding="utf-8")
        return __import__("subprocess").CompletedProcess(argv, 0, "Godot Engine v4.7.stable\n", "")

    real_run = staticmethod(__import__("subprocess").run)

    def outside(self, argv, *args, **kw):
        # Only `patch` may run outside the sandbox: it applies the change to the copy.
        if argv[0] != "patch":
            raise AssertionError(f"started outside: {argv}")
        return self.real_run(argv, *args, **kw)

    def replay(self, game, **kw):
        with mock.patch.object(box, "probe", return_value=(FAKE, None)), \
                mock.patch.object(box, "run", side_effect=self.engine), \
                mock.patch.object(hr.subprocess, "run", side_effect=self.outside):
            return hr.run(self.route, self.tmp / "out", game=game, godot=self.godot, sandbox="require",
                          capture_frames=False, **kw)

    def crate_copy(self, viewport=None):
        game = self.tmp / "crate"
        shutil.copytree(CRATE, game)
        if viewport is not None:
            path = game / FILENAME
            doc = json.loads(path.read_text(encoding="utf-8"))
            doc["viewport"] = viewport
            path.write_text(json.dumps(doc), encoding="utf-8")
        return game

    def test_a_config_beside_the_game_that_disagrees_starts_nothing(self):
        with self.assertRaises(SystemExit) as caught:
            self.replay(self.crate_copy([800, 480]))
        self.assertIn("viewport", str(caught.exception))
        self.assertIn("[640, 360]", str(caught.exception))
        self.assertEqual(self.calls, [])

    def test_a_base_config_given_to_the_game_is_compared_too(self):
        config = read_game(CRATE)
        with self.assertRaises(SystemExit) as caught:
            self.replay(self.crate_copy(), project=dict(config, physicsTicksPerSecond=120))
        self.assertIn("physicsTicksPerSecond", str(caught.exception))
        self.assertEqual(self.calls, [])

    def test_a_change_that_moves_the_games_setting_is_refused_on_the_copy(self):
        game = self.crate_copy()
        import difflib
        before = (game / "project.godot").read_text(encoding="utf-8")
        after = before.replace("viewport_width=640", "viewport_width=800")
        self.assertNotEqual(before, after)
        change = self.tmp / "change.patch"
        change.write_text("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                                       "a/project.godot", "b/project.godot")), encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.replay(game, patches=[change])
        self.assertIn("after the change under test", str(caught.exception))
        self.assertIn("[800, 360]", str(caught.exception))
        self.assertFalse([argv for argv in self.calls if "--import" not in argv])

    def test_a_matching_config_still_replays(self):
        self.replay(self.crate_copy())
        self.assertTrue(any("--import" not in argv for argv in self.calls))


if __name__ == "__main__":
    unittest.main()
