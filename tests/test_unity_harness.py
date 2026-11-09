"""The Unity harness: harness/unity/run.py with a fake player, the per-game map against Platformio's own
files, the package's shape, and the trace contract's objects field on both sides.

No Unity runs here. tests/unity_fake_player.py writes what the C# harness writes, so these tests
cover the runner (patching, the environment allowlist, the output checks, the replay document)
and say nothing about whether the C# compiles or records the game correctly.
"""
from __future__ import annotations

import copy
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from expectrail.contracts import ContractError, validate
from harness import run as godot_run
from harness.unity import run as unity

REPO = godot_run.REPO
GAME = REPO / "game" / "unity-platformer"
ASSETS = GAME / "Assets" / "_Project"
MAP = json.loads((REPO / "harness" / "unity" / "maps" / "unity-platformer.json").read_text())
FAKE = REPO / "tests" / "unity_fake_player.py"
CANARY = REPO / "harness" / "unity" / "fixtures" / "canary-env.patch"
SMOKE = REPO / "harness" / "routes" / "unity-smoke.json"
EXAMPLES = REPO / "contracts" / "examples"


def route(tmp: Path, ticks: int = 4, events=None) -> Path:
    path = tmp / "route.json"
    path.write_text(json.dumps({"format": "expectrail.route/v0", "name": "tiny", "ticks": ticks, "seed": 7,
                                "events": events if events is not None else [
                                    {"tick": 1, "action": "move_right", "pressed": True},
                                    {"tick": 2, "action": "jump", "pressed": True}]}))
    return path


def player(tmp: Path, patches=(), mode=None, name="clean") -> Path:
    """A build folder as the Unity workflow leaves one: build.json with the key, and the player."""
    folder = tmp / "players" / name
    (folder / "player").mkdir(parents=True)
    key = unity.build_key(GAME, [Path(p) for p in patches])
    (folder / "build.json").write_text(json.dumps(dict(key, player=unity.PLAYER)))
    exe = folder / unity.PLAYER
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" --mode "{folder / "fake-mode.json"}" "$@"\n')
    exe.chmod(0o755)
    if mode is not None:
        (folder / "fake-mode.json").write_text(json.dumps(mode))
    return folder



def _code_only(text: str) -> str:
    """C# source without its comments, string literals and character literals (interpolation holes
    are dropped with the strings, which is enough for counting brackets)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c, nxt = text[i], text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            i = text.find("\n", i)
            i = n if i < 0 else i
        elif c == "/" and nxt == "*":
            i = text.index("*/", i) + 2
        elif c in "\"'":
            quote, i = c, i + 1
            while i < n and text[i] != quote:
                i += 2 if text[i] == "\\" else 1
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)

class FakePlayerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # A display is there, so the runner does not wrap the fake in xvfb-run.
        patcher = mock.patch.dict(os.environ, {"DISPLAY": ":99"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def replay(self, mode=None, patches=(), ticks=4, **kw):
        folder = player(self.tmp, patches, mode)
        return unity.run(route(self.tmp, ticks), self.tmp / "out", list(patches), player=folder, **kw)


class RunnerTest(FakePlayerCase):
    def test_a_clean_replay_writes_the_godot_harness_outputs(self):
        replay = self.replay()
        out = self.tmp / "out"
        self.assertEqual(validate(replay, "replay"), "replay")
        self.assertEqual(json.loads((out / "replay.json").read_text()), replay)
        self.assertEqual(replay["engine"]["name"], "unity")
        self.assertEqual(replay["engine"]["version"], "6000.3.21f1")
        self.assertEqual(replay["engine"]["renderer"], "OpenGLCore OpenGL 4.5 (fake)")
        self.assertEqual(replay["engine"]["device"], unity.cpu_model())
        self.assertEqual(replay["capture"], {"fps": 50, "physicsTicksPerSecond": 50, "frames": 4,
                                             "pattern": "frames/f%08d.png"})
        frames = sorted((out / "frames").glob("*.png"))
        self.assertEqual([p.name for p in frames], [f"f{i:08d}.png" for i in range(4)])
        self.assertEqual(replay["frameSha256"], [unity.sha256_file(p) for p in frames])
        self.assertEqual(replay["trace"], {"path": "trace.json", "sha256": unity.sha256_file(out / "trace.json")})
        self.assertEqual(replay["route"]["sha256"], unity.sha256_file(self.tmp / "route.json"))
        self.assertEqual(replay["game"], {"tree": unity.tree_digest(GAME), "patch": None, "patchSha256": None})
        self.assertEqual(replay["seed"], 7)
        self.assertEqual(replay["build"]["key"], unity.build_key(GAME, [])["key"])
        self.assertEqual(replay["settle"], {"ticks": 76, "frozenFrames": 3})
        self.assertEqual(replay["integrity"]["errors"], 1)
        self.assertEqual(replay["hazards"][0]["kind"], "real-time-fade")
        self.assertTrue((out / "unity.log").is_file())

    def test_the_player_gets_the_route_map_seed_and_window_it_needs(self):
        self.replay()
        log = (self.tmp / "out" / "unity.log").read_text()
        argv = json.loads(re.search(r"^ARGS=(.*)$", log, re.M).group(1))
        for flag, value in (("-expectrail-route", str((self.tmp / "route.json").resolve())),
                            ("-expectrail-map", str(unity.map_path(GAME).resolve())),
                            ("-expectrail-out", str((self.tmp / "out").resolve())), ("-expectrail-seed", "7"),
                            ("-screen-width", "1600"), ("-screen-height", "960"), ("-screen-fullscreen", "0"),
                            ("-logFile", "-")):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertIn("-force-glcore", argv)
        # A window and a graphics device are needed to draw the frames.
        self.assertNotIn("-batchmode", argv)
        self.assertNotIn("-nographics", argv)

    def test_without_a_display_the_player_runs_under_xvfb(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISPLAY", None)
            cmd = unity.player_cmd(Path("/p/game.x86_64"), Path("r.json"), Path("m.json"), Path("o"), 1, MAP, True)
        self.assertEqual(cmd[:4], ["xvfb-run", "-a", "-s", "-screen 0 1920x1080x24"])

    def test_the_game_sees_only_the_allowlisted_environment_and_a_fresh_home(self):
        secrets = {"EXPECTRAIL_CANARY": "canary-1234", "EXPECTRAIL_HELDOUT_DIR": "/canary/private/path",
                   "META_API_KEY": "meta-key", "UNITY_PASSWORD": "unity-password", "GITHUB_TOKEN": "gh-token"}
        with mock.patch.dict(os.environ, secrets):
            self.replay()
        log = (self.tmp / "out" / "unity.log").read_text()
        self.assertIn("CANARY_ENV=\n", log)
        self.assertIn("CANARY_HELDOUT=\n", log)
        for value in secrets.values():
            self.assertNotIn(value, log)
        # PWD, SHLVL and _ are set by the fake's own /bin/sh wrapper, not passed by the runner.
        keys = [k for k in re.search(r"^ENV_KEYS=(.*)$", log, re.M).group(1).split(",") if k not in ("PWD", "SHLVL", "_")]
        allowed = [k for k in keys if k in godot_run.GAME_ENV_KEEP or k.startswith(godot_run.GAME_ENV_PREFIXES)]
        self.assertEqual(keys, allowed)
        home = self.tmp / "out" / "home"
        self.assertIn(f"HOME={home}\n", log)
        env = unity.player_env(self.tmp / "h")
        self.assertEqual((env["LP_NATIVE_VECTOR_WIDTH"], env["LP_NUM_THREADS"], env["GALLIUM_DRIVER"]),
                         ("128", "4", "llvmpipe"))

    def test_patches_apply_in_order_to_a_copy_and_name_the_player(self):
        replay = self.replay(patches=[CANARY])
        work = self.tmp / "out" / "work" / "Assets/_Project/Scripts/Platformio/Character/PlayerController.cs"
        self.assertIn("CANARY_ENV=", work.read_text())
        self.assertNotIn("CANARY_ENV=", (GAME / "Assets/_Project/Scripts/Platformio/Character/PlayerController.cs").read_text())
        self.assertEqual(replay["game"]["patch"], str(CANARY))
        self.assertEqual(replay["game"]["patchSha256"], unity.sha256_file(CANARY))
        self.assertEqual(replay["game"]["tree"], unity.tree_digest(GAME))  # the clean game, as harness/run.py names it

    def test_a_patch_that_does_not_apply_is_a_failure(self):
        bad = self.tmp / "bad.patch"
        bad.write_text("--- a/Assets/nothing.cs\n+++ b/Assets/nothing.cs\n@@ -1,1 +1,1 @@\n-a\n+b\n")
        with self.assertRaises(SystemExit) as caught:
            self.replay(patches=[bad])
        self.assertIn("does not apply", str(caught.exception))

    def test_a_player_built_from_other_files_is_refused(self):
        folder = player(self.tmp)  # built clean
        with self.assertRaises(SystemExit) as caught:
            unity.run(route(self.tmp), self.tmp / "out", [CANARY], player=folder)
        self.assertIn("no player", str(caught.exception))
        with self.assertRaises(SystemExit) as caught:
            unity.run(route(self.tmp), self.tmp / "out", [], player=None)
        self.assertIn("no Unity player given", str(caught.exception))

    def test_a_folder_of_players_gives_the_one_built_from_this_patch_set(self):
        player(self.tmp, name="clean")
        player(self.tmp, [CANARY], name="canary")
        replay = unity.run(route(self.tmp), self.tmp / "out", [CANARY], player=self.tmp / "players")
        self.assertEqual(replay["build"]["key"], unity.build_key(GAME, [CANARY])["key"])
        with mock.patch.dict(os.environ, {"EXPECTRAIL_UNITY_PLAYER": str(self.tmp / "players")}):
            self.assertEqual(unity.run(route(self.tmp), self.tmp / "out2")["build"]["key"],
                             unity.build_key(GAME, [])["key"])

    def test_a_frame_with_zero_or_two_physics_steps_fails_the_run(self):
        for n in (0, 2):
            with self.subTest(steps=n), self.assertRaises(SystemExit) as caught:
                self.replay({"steps": {"2": n}})
            self.assertIn(f"frame 2 held {n} physics steps", str(caught.exception))
            shutil.rmtree(self.tmp / "players")

    def test_missing_or_wrong_frames_fail_the_run(self):
        cases = {"dropFrame": (2, "3 frames for 4 ticks"), "frameSize": ([800, 600], "is 800 x 600, not 1600 x 960")}
        for key, (value, message) in cases.items():
            with self.subTest(mode=key), self.assertRaises(SystemExit) as caught:
                self.replay({key: value})
            self.assertIn(message, str(caught.exception))
            shutil.rmtree(self.tmp / "players")

    def test_a_short_gapped_or_malformed_trace_fails_the_run(self):
        cases = {"rows": (3, "3 rows for 4 ticks"), "tickGap": (True, "row 1 is tick 5"),
                 "badObject": (True, "contracts/trace.schema.json"), "tps": (60, "60 physics ticks a second")}
        for key, (value, message) in cases.items():
            with self.subTest(mode=key), self.assertRaises(SystemExit) as caught:
                self.replay({key: value})
            self.assertIn(message, str(caught.exception))
            shutil.rmtree(self.tmp / "players")

    def test_a_player_that_fails_is_a_failure_and_its_log_is_kept(self):
        cases = {"exit": (1, "failed (1) without a trace"), "noTrace": (True, "without a trace"),
                 "error": ("settle: TimeoutException: the game did not settle", "the harness failed in the player")}
        for key, (value, message) in cases.items():
            with self.subTest(mode=key), self.assertRaises(SystemExit) as caught:
                self.replay({key: value})
            self.assertIn(message, str(caught.exception))
            self.assertIn("CANARY_ENV=", (self.tmp / "out" / "unity.log").read_text())
            shutil.rmtree(self.tmp / "players")

    def test_a_player_that_hangs_times_out(self):
        with mock.patch.object(unity, "TIMEOUT", 1), self.assertRaises(SystemExit) as caught:
            self.replay({"sleep": 5})
        self.assertIn("timed out", str(caught.exception))
        self.assertIn("did not finish", (self.tmp / "out" / "unity.log").read_text())

    def test_the_route_must_be_current_known_and_in_the_games_ticks(self):
        folder = player(self.tmp)
        bad = {"unknown action": ([{"tick": 0, "action": "dash", "pressed": True}], "'dash'"),
               "late event": ([{"tick": 9, "action": "jump", "pressed": True}], "outside the route's 4 ticks")}
        for name, (events, message) in bad.items():
            with self.subTest(name), self.assertRaises(SystemExit) as caught:
                unity.run(route(self.tmp, events=events), self.tmp / "out", player=folder)
            self.assertIn(message, str(caught.exception))
        old = self.tmp / "old.json"
        old.write_text(json.dumps({"format": "nightshift.route/v0", "name": "x", "ticks": 2, "events": []}))
        with self.assertRaises(SystemExit):
            unity.run(old, self.tmp / "out", player=folder)
        with self.assertRaises(SystemExit) as caught:
            unity.run(route(self.tmp), self.tmp / "out", player=folder, fps=60)
        self.assertIn("one frame per tick", str(caught.exception))

    def test_trace_only_replays_write_no_frames(self):
        replay = self.replay(capture_frames=False)
        self.assertEqual(replay["capture"]["frames"], 0)
        self.assertEqual(replay["frameSha256"], [])
        self.assertIn("-expectrail-no-frames", (self.tmp / "out" / "unity.log").read_text())

    def test_a_second_run_in_the_same_folder_starts_clean(self):
        self.replay()
        (self.tmp / "out" / "home" / "stale").write_text("x")
        shutil.rmtree(self.tmp / "players")
        with self.assertRaises(SystemExit):
            self.replay({"noTrace": True})  # the first run's trace.json is not reused
        self.assertFalse((self.tmp / "out" / "home" / "stale").exists())


class ReplayCheckTest(FakePlayerCase):
    """Two replays compared by frame hashes and trace hash (run.py --compare, as CI does), and N replays
    through the shared harness.replay_check --adapter unity."""

    def two(self, mode=None):
        folder = player(self.tmp, mode=mode)
        r = route(self.tmp)
        for i in range(2):
            unity.run(r, self.tmp / f"run-{i:02d}", player=folder)
        out = io.StringIO()
        with redirect_stdout(out):
            code = unity.main(["--out", str(self.tmp / "run-00"), "--compare", str(self.tmp / "run-01")])
        return code, json.loads(out.getvalue())

    def test_two_identical_replays_compare_identical(self):
        code, result = self.two()
        self.assertEqual(code, 0)
        self.assertEqual(result["framesDiffer"], [])
        self.assertFalse(result["traceDiffers"])

    def test_replays_that_differ_fail_and_say_which_frames(self):
        code, result = self.two({"vary": True})
        self.assertEqual(code, 1)
        self.assertEqual(result["framesDiffer"], [0, 1, 2, 3])
        self.assertFalse(result["traceDiffers"])

    def test_compare_counts_missing_frames_and_the_trace(self):
        a = {"frameSha256": ["x", "y"], "trace": {"sha256": "t"}}
        b = {"frameSha256": ["x"], "trace": {"sha256": "u"}}
        self.assertEqual(unity.compare(a, b), {"framesDiffer": [1], "traceDiffers": True, "identical": False})

    def test_the_shared_replay_check_runs_unity_through_its_adapter(self):
        from harness import adapters, replay_check

        folder = player(self.tmp)
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"EXPECTRAIL_UNITY_PLAYER": str(folder)}), redirect_stdout(out):
            code = replay_check.main(["--adapter", "unity", "--route", str(route(self.tmp)), "--runs", "2",
                                      "--out", str(self.tmp / "check")])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("2 of 2 runs identical", out.getvalue())
        unity_adapter = adapters.get("unity")
        self.assertEqual(unity_adapter.engine, json.loads((self.tmp / "check" / "run-00" / "replay.json").read_text())["engine"]["name"])
        self.assertEqual(unity_adapter.tree_digest(), unity.tree_digest(GAME))
        self.assertEqual(unity_adapter.ticks_per_second, MAP["physicsTicksPerSecond"])
        self.assertEqual(unity_adapter.default_route, SMOKE)
        self.assertEqual(len(unity_adapter.frames(self.tmp / "check" / "run-01")), 4)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_prepare_build_lays_out_a_patched_copy_with_the_package(self):
        before = unity.tree_digest(GAME)
        key = unity.prepare_build(self.tmp / "b", [CANARY])
        project = self.tmp / "b" / "project"
        manifest = json.loads((project / "Packages" / "manifest.json").read_text())
        self.assertEqual(manifest["dependencies"]["com.expectrail.harness"], "file:../../com.expectrail.harness")
        package = (project / "Packages" / "../../com.expectrail.harness").resolve()
        self.assertEqual(package, (self.tmp / "b" / "com.expectrail.harness").resolve())
        self.assertEqual(unity.tree_digest(package, ()), unity.tree_digest(unity.PACKAGE, ()))
        self.assertIn('fullname="Expectrail.Harness"', (project / "Assets" / "ExpectrailHarness" / "link.xml").read_text())
        config = json.loads((project / "expectrail-build.json").read_text())
        self.assertEqual(config, {"startScene": MAP["scene"], "player": "../player/game.x86_64", "width": 1600,
                                  "height": 960})
        self.assertIn("CANARY_ENV=", (project / "Assets/_Project/Scripts/Platformio/Character/PlayerController.cs").read_text())
        built = json.loads((self.tmp / "b" / "build.json").read_text())
        self.assertEqual(built["key"], unity.build_key(GAME, [CANARY])["key"])
        self.assertEqual(built, key)
        self.assertEqual(built["player"], "player/game.x86_64")
        # Everything but the manifest, the link.xml and the build config is the patched game.
        self.assertEqual(unity.tree_digest(GAME), before)

    def test_the_copy_leaves_out_the_editors_own_folders(self):
        game = self.tmp / "game"
        shutil.copytree(GAME / "ProjectSettings", game / "ProjectSettings")
        (game / "Assets").mkdir()
        (game / "Assets" / "a.cs").write_text("x")
        for name in unity.UNITY_IGNORE:
            (game / name).mkdir()
            (game / name / "junk").write_text("y")
        digest = unity.tree_digest(game)
        unity._copy_game(game, self.tmp / "copy")
        self.assertEqual(sorted(p.name for p in (self.tmp / "copy").iterdir()), ["Assets", "ProjectSettings"])
        for name in unity.UNITY_IGNORE:
            shutil.rmtree(game / name)
        self.assertEqual(unity.tree_digest(game), digest)
        self.assertEqual(godot_run.tree_digest(game), digest)  # the same bytes as the Godot harness's digest

    def test_the_build_key_changes_with_the_patches_and_the_package(self):
        clean, canary = unity.build_key(GAME, []), unity.build_key(GAME, [CANARY])
        self.assertNotEqual(clean["key"], canary["key"])
        self.assertEqual(clean["key"], unity.build_key(GAME, [])["key"])
        self.assertEqual(clean["unityVersion"], "6000.3.21f1")
        package = self.tmp / "pkg"
        shutil.copytree(unity.PACKAGE, package)
        (package / "Runtime" / "Extra.cs").write_text("// changed")
        with mock.patch.object(unity, "PACKAGE", package):
            self.assertNotEqual(unity.build_key(GAME, [])["key"], clean["key"])
        self.assertIsNone(unity.build_key(GAME, [], harness=False)["package"])


class MapTest(unittest.TestCase):
    """harness/unity/maps/unity-platformer.json against the game's own files."""

    @classmethod
    def setUpClass(cls):
        cls.actions = json.loads((ASSETS / "Global" / "InputSystem" / "GlobalInputActions.inputactions").read_text())
        cls.scripts = {p: p.read_text() for p in (ASSETS / "Scripts").rglob("*.cs")}

    def has_class(self, full_name: str) -> bool:
        namespace, _, name = full_name.rpartition(".")
        return any(f"namespace {namespace}" in text and re.search(rf"\bclass {name}\b", text)
                   for text in self.scripts.values())

    def test_route_actions_are_keys_bound_to_the_games_actions(self):
        maps = {m["name"]: m for m in self.actions["maps"]}
        for a in MAP["actions"]:
            with self.subTest(action=a["name"]):
                map_name, action = a["inputAction"].split("/")
                bindings = [b for b in maps[map_name]["bindings"] if b["action"] == action]
                control = a["key"][0].lower() + a["key"][1:]
                self.assertIn(f"<Keyboard>/{control}", [b["path"] for b in bindings])
                self.assertEqual(a["device"], "Keyboard")
        names = [a["name"] for a in MAP["actions"]]
        self.assertEqual(len(names), len(set(names)))

    def test_no_player_action_has_an_interaction_that_would_time_presses(self):
        player = next(m for m in self.actions["maps"] if m["name"] == "Player")
        self.assertEqual([a["interactions"] for a in player["actions"]], ["", "", ""])
        self.assertTrue(all(not b["interactions"] for b in player["bindings"]))

    def test_the_devices_satisfy_the_keyboard_scheme(self):
        scheme = next(s for s in self.actions["controlSchemes"] if s["name"] == "Keyboard&Mouse")
        required = [d["devicePath"].strip("<>") for d in scheme["devices"] if not d["isOptional"]]
        self.assertEqual(sorted(required), sorted(MAP["devices"]))

    def test_roles_settle_and_floor_name_the_games_own_components(self):
        for name in [r["component"] for r in MAP["roles"]] + [f["component"] for f in MAP["settle"]["fades"]] \
                + MAP["settle"]["seenThenGone"]:
            with self.subTest(component=name):
                self.assertTrue(self.has_class(name), name)
        self.assertEqual({r["role"] for r in MAP["roles"]}, {"player", "coin", "enemy", "projectile"})
        tags = (GAME / "ProjectSettings" / "TagManager.asset").read_text()
        self.assertIn("  - Enemy\n", tags)
        self.assertIn("m_TagString: Player", (ASSETS / "GameLoop/Character/Player/Player.prefab").read_text())
        self.assertIn("m_TagString: Enemy", (ASSETS / "GameLoop/Character/Enemy/Enemy.prefab").read_text())
        for layer in MAP["player"]["onFloorLayers"]:
            self.assertIn(f"  - {layer}\n", tags)
        self.assertIn("IsTouchingLayers(LayerMask.GetMask(\"Ground\"))",
                      self.scripts[ASSETS / "Scripts/Platformio/Character/PlayerController.cs"])
        self.assertIn("Time.unscaledDeltaTime", self.scripts[ASSETS / "Scripts/Platformio/UI/Fader.cs"])

    def test_ground_scene_rate_and_scale_are_the_games(self):
        base = (ASSETS / "GameLoop/Level/BaseLevel.prefab").read_text()
        for name in MAP["ground"]["tilemaps"]:
            self.assertIn(f"m_Name: {name}\n", base)
        self.assertIn("m_Layer: 6\n  m_Name: PlatformsTilemap\n", base)  # the Ground layer
        from agents.observations import BODY_HALF_WIDTH, SINK_WINDOW
        self.assertEqual((MAP["ground"]["sinkWindowPx"], MAP["ground"]["bodyHalfWidthPx"]), (SINK_WINDOW, BODY_HALF_WIDTH))
        build = (GAME / "ProjectSettings" / "EditorBuildSettings.asset").read_text()
        self.assertIn(f"path: {MAP['scene']}", build)
        step = float(re.search(r"Fixed Timestep: ([\d.]+)", (GAME / "ProjectSettings/TimeManager.asset").read_text()).group(1))
        self.assertEqual(MAP["physicsTicksPerSecond"], round(1 / step))
        for sheet in ("GameLoop/Environment/Ground/Grass/Spritesheet/spritesheet_ground.png.meta",
                      "GameLoop/Character/Player/Appearance/spritesheet_players.png.meta"):
            self.assertIn(f"spritePixelsToUnits: {MAP['pixelsPerUnit']}\n", (ASSETS / sheet).read_text())
        self.assertEqual((MAP["frameWidth"], MAP["frameHeight"]), (1600, 960))

    def test_the_smoke_route_uses_the_maps_actions_in_the_games_ticks(self):
        doc = json.loads(SMOKE.read_text())
        self.assertEqual(validate(doc, "route"), "route")
        unity.check_route(doc, MAP)
        self.assertEqual(doc["ticks"] / MAP["physicsTicksPerSecond"], 4.0)

    def test_the_canary_patch_applies_to_the_clean_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            unity._copy_game(GAME, Path(tmp) / "g")
            godot_run.apply_patches(Path(tmp) / "g", [CANARY])


class PackageTest(unittest.TestCase):
    PACKAGE = unity.PACKAGE

    def test_the_package_is_com_expectrail_harness_and_compiles_only_with_the_define(self):
        pkg = json.loads((self.PACKAGE / "package.json").read_text())
        self.assertEqual(pkg["name"], "com.expectrail.harness")
        self.assertIn("com.unity.inputsystem", pkg["dependencies"])
        runtime = json.loads((self.PACKAGE / "Runtime" / "Expectrail.Harness.asmdef").read_text())
        self.assertEqual(runtime["references"], ["Unity.InputSystem"])
        self.assertEqual(runtime["defineConstraints"], ["EXPECTRAIL_HARNESS"])
        editor = json.loads((self.PACKAGE / "Editor" / "Expectrail.Harness.Editor.asmdef").read_text())
        self.assertEqual(editor["includePlatforms"], ["Editor"])
        self.assertEqual(editor["defineConstraints"], [])
        self.assertIn("[assembly: AlwaysLinkAssembly]", (self.PACKAGE / "Runtime" / "AssemblyInfo.cs").read_text())

    def test_the_build_method_and_its_settings(self):
        text = (self.PACKAGE / "Editor" / "HarnessBuild.cs").read_text()
        namespace = re.search(r"namespace (\S+)", text).group(1)
        cls = re.search(r"public static class (\w+)", text).group(1)
        self.assertEqual(f"{namespace}.{cls}.Build", unity.BUILD_METHOD)
        for needle in ("ScriptingImplementation.Mono2x", "ManagedStrippingLevel.Minimal", "GraphicsDeviceType.OpenGLCore",
                       "BuildTarget.StandaloneLinux64", "extraScriptingDefines", "FullScreenMode.Windowed",
                       "runInBackground = true", "Expectrail.Harness.dll"):
            self.assertIn(needle, text)

    def test_the_runtime_uses_the_documented_entry_points(self):
        text = "\n".join(p.read_text() for p in (self.PACKAGE / "Runtime").glob("*.cs"))
        for needle in ("RuntimeInitializeLoadType.SubsystemRegistration", "RuntimeInitializeLoadType.BeforeSceneLoad",
                       "Time.captureDeltaTime = Time.fixedDeltaTime", "QualitySettings.vSyncCount = 0",
                       "Random.InitState", "PlayerLoop.SetPlayerLoop", "InputSystem.QueueStateEvent",
                       "InputSystem.AddDevice<Keyboard>", "InputSystem.RemoveDevice", "BackgroundBehavior.IgnoreFocus",
                       "WaitForEndOfFrame", "ScreenCapture.CaptureScreenshotAsTexture", "Application.logMessageReceived",
                       "AnimatorUpdateMode.UnscaledTime", "useAutoRandomSeed", "GeometryUtility.TestPlanesAABB",
                       "Camera.main", "flipX", "lossyScale", "IsTouchingLayers", "CompositeCollider2D"):
            self.assertIn(needle, text)
        # Not the legacy input manager, and nothing from the Editor-only Unity Recorder.
        self.assertNotRegex(text, r"\bUnityEngine\.Input\.|\bInput\.Get(Key|Axis|Button)")
        self.assertNotIn("UnityEditor", text)
        self.assertNotIn("Recorder.Input", text)
        self.assertNotIn("GetInstanceID", text)  # obsolete in 6.3
        # A crude check, short of a compiler, that every file's brackets balance outside strings,
        # characters and comments.
        for p in list((self.PACKAGE / "Runtime").glob("*.cs")) + list((self.PACKAGE / "Editor").glob("*.cs")):
            code = _code_only(p.read_text())
            with self.subTest(file=p.name):
                for a, b in ("{}", "()", "[]"):
                    self.assertEqual(code.count(a), code.count(b), (a, b))


class TraceContractTest(unittest.TestCase):
    """contracts/trace.schema.json and its objects field: the writer (the fake, and the C# by shape)
    and the readers (the runner, the frozen normalizer, the observations stand-in, the gameplay check)."""

    @classmethod
    def setUpClass(cls):
        cls.example = json.loads((EXAMPLES / "trace.json").read_text())

    def test_the_example_validates_and_bad_objects_do_not(self):
        self.assertEqual(validate(self.example, "trace"), "trace")
        for change in ({"box": [1, 2, 3]}, {"role": "tree"}, {"visible": "yes"}, {"extra": 1}, {"id": ""}):
            doc = copy.deepcopy(self.example)
            doc["rows"][0]["objects"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ContractError):
                validate(doc, "trace")

    def test_a_godot_shaped_trace_still_validates(self):
        rows = [{"tick": t, "frame": t // 2, "player": [90.0 + t, 636.75], "onFloor": True, "ground": 650.0,
                 "facing": 1, "coins": [[700.0, 610.0]], "enemies": [[0, 545.1, 358.06]], "projectiles": [],
                 "view": [2.0, 0.0, 0.0, 2.0, 620.0, -520.0]} for t in range(4)]
        doc = {"format": "expectrail.trace/v0", "ticks": 4, "physicsTicksPerSecond": 120, "rows": rows,
               "capabilities": {"enemies": "initial-instances", "projectiles": "complete", "facing": True, "onFloor": True},
               "levelSurfaces": [[[-704.0, 0.0], [-768.0, 0.0], [-768.0, 64.0]]],
               "levelArt": {"x0": -832, "y0": -768, "width": 1, "height": 1664, "columns": [[[0, 64]]]}}
        self.assertEqual(validate(doc, "trace"), "trace")

    def test_the_unity_replay_example_validates_and_engine_names_are_closed(self):
        doc = json.loads((EXAMPLES / "replay-unity.json").read_text())
        self.assertEqual(validate(doc, "replay"), "replay")
        self.assertEqual(validate(json.loads((EXAMPLES / "replay.json").read_text()), "replay"), "replay")
        doc["engine"]["name"] = "unreal"
        with self.assertRaises(ContractError):
            validate(doc, "replay")

    def test_the_frozen_normalizer_ignores_the_objects_field(self):
        from expectrail.trace.normalize import normalize

        route_doc = json.loads(SMOKE.read_text())
        without = copy.deepcopy(self.example)
        for row in without["rows"]:
            row.pop("objects")
        a = normalize(self.example, route_doc, episode_id="x", trace_bytes=b"same")
        b = normalize(without, route_doc, episode_id="x", trace_bytes=b"same")
        self.assertEqual(a, b)
        self.assertEqual(a["frameMapping"], None)
        with_replay = normalize(self.example, route_doc, episode_id="x", replay={"capture": {"fps": 50}})
        self.assertEqual(with_replay["frameMapping"], {"protocol": "tick-step/v1", "step": 1})

    def test_the_observations_and_gameplay_readers_run_on_a_unity_trace(self):
        from agents.gameplay import judge_trace
        from agents.observations import engine_refs_by_frame, from_trace_synthetic

        obs = from_trace_synthetic(self.example, fps=50)
        self.assertEqual(validate(obs, "observations"), "observations")
        self.assertEqual(len(obs["frames"]), len(self.example["rows"]))
        refs = engine_refs_by_frame(self.example, (1600, 960), [0, 1], fps=50)
        self.assertEqual(sorted(refs), [0, 1])
        self.assertIn(judge_trace(self.example, min_delta_x=1.0)["result"], ("pass", "fail", "needs-review"))

    def test_the_runner_reads_visible_boxes_by_frame(self):
        boxes = unity.visible_boxes(self.example, "player")
        self.assertEqual(sorted(boxes), [r["frame"] for r in self.example["rows"]])
        self.assertEqual(boxes[0], [self.example["rows"][0]["objects"][0]["box"]])
        self.assertEqual(unity.visible_boxes(self.example, "enemy")[0], [])  # not visible: no box counted
        self.assertEqual(unity.visible_boxes({"rows": [{"tick": 0}]}, "player"), {})


if __name__ == "__main__":
    unittest.main()
