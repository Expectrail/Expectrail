"""The engine-adapter boundary (harness/adapters.py): one run signature, the Godot digest unchanged."""
from __future__ import annotations

import json
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
    def test_godot_unity_and_web_are_registered(self):
        self.assertEqual(adapters.names(), ("godot", "unity", "web"))
        self.assertIs(adapters.resolve("web"), adapters.get("web"))
        self.assertIs(adapters.resolve(adapters.GODOT), adapters.GODOT)
        self.assertIs(adapters.get("unity"), adapters.UNITY)  # registered with its runner, harness/unity/run.py
        with self.assertRaises(KeyError):
            adapters.get("unreal")

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

    def test_every_adapter_s_engine_is_one_the_replay_contract_accepts(self):
        from expectrail.contracts import schema

        allowed = schema("replay")["properties"]["engine"]["properties"]["name"]["enum"]
        for name in adapters.names():
            self.assertIn(adapters.get(name).engine, allowed, name)
        self.assertIn("unity", allowed)

    def test_frames_are_found_by_the_pattern_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = Path(tmp) / "frames"
            frames.mkdir()
            for n in (2, 0, 10, 1):
                (frames / f"f{n:08d}.png").write_bytes(b"")
            (frames / "notes.txt").write_text("")
            got = adapters.get("godot").frames(Path(tmp))
        self.assertEqual([p.name for p in got], ["f00000000.png", "f00000001.png", "f00000002.png", "f00000010.png"])


@unittest.skipUnless(__import__("importlib").util.find_spec("playwright"), "playwright is not installed")
class WebReplayTest(unittest.TestCase):
    def test_the_web_adapter_writes_the_document_the_web_harness_writes(self):
        from harness.web import run as web

        route = adapters.get("web").default_route
        bug = sorted(adapters.get("web").bugs.glob("layering/v1.patch"))
        with tempfile.TemporaryDirectory() as tmp:
            try:
                direct = web.run(route, Path(tmp) / "direct", bug)
            except Exception as exc:  # noqa: BLE001 - no browser on this machine
                self.skipTest(f"chromium unavailable: {exc}")
            through = adapters.get("web").run(route, Path(tmp) / "adapter", bug)
            self.assertEqual((Path(tmp) / "direct" / "replay.json").read_bytes(),
                             (Path(tmp) / "adapter" / "replay.json").read_bytes())
            self.assertEqual((Path(tmp) / "direct" / "trace.json").read_bytes(),
                             (Path(tmp) / "adapter" / "trace.json").read_bytes())
        self.assertEqual(through, direct)
        self.assertEqual(through["engine"]["name"], adapters.get("web").engine)


def fake_godot(route, out, patch=None, game=None, fps=60, godot=None, patches=None, force_import=False,
               capture_frames=True):
    """harness.run.run's signature and outputs (frames, trace.json, replay.json), with no Godot: the
    robot stands 10 px lower for each patch applied."""
    out = Path(out)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    y = 452 + 10 * len(patches or [])
    rows = [{"tick": t, "player": [210.0, float(y)], "view": [1, 0, 0, 1, t, 0]} for t in range(4)]
    for n in range(2):
        (out / "frames" / f"f{n:08d}.png").write_text(f"frame {n} y {y}")
    (out / "trace.json").write_text(json.dumps({"format": "expectrail.trace/v0", "rows": rows}))
    replay = {"frameSha256": [adapters.sha256_file(f) for f in sorted((out / "frames").glob("f*.png"))],
              "trace": {"sha256": adapters.sha256_file(out / "trace.json")}, "fps": fps}
    (out / "replay.json").write_text(json.dumps(replay))
    return replay


class HarnessToolDefaultsTest(unittest.TestCase):
    """Without --adapter, replay_check and check_seeded replay the Godot game as they did."""

    def test_replay_check_defaults_to_godot(self):
        import io
        from contextlib import redirect_stdout

        from harness import replay_check

        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()) as printed, \
                mock.patch.object(godot_harness, "run", side_effect=fake_godot) as run:
            code = replay_check.main(["--route", "harness/routes/smoke.json", "--runs", "2", "--out", tmp])
            summary = json.loads((Path(tmp) / "summary.json").read_text())
        self.assertEqual(code, 0)
        self.assertEqual(printed.getvalue().splitlines(), ["run 0: reference (2 frames)", "run 1: identical",
                                                           "2 of 2 runs identical to the first"])
        self.assertEqual(summary, {"route": "harness/routes/smoke.json", "patches": None, "runs": 2, "identical": 2})
        self.assertEqual(run.call_args.kwargs, {"patches": None, "game": None, "fps": 60, "capture_frames": True})

    def test_check_seeded_defaults_to_the_godot_bugs_and_the_smoke_route(self):
        import io
        from contextlib import redirect_stdout

        from harness import check_seeded

        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()), \
                mock.patch.object(godot_harness, "run", side_effect=fake_godot) as run:
            code = check_seeded.main(["--out", tmp, "--only", "layering/v1", "sinking/v2"])
            summary = json.loads((Path(tmp) / "summary.json").read_text())
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args_list[0].args[0], REPO / "harness" / "routes" / "smoke.json")
        self.assertEqual(summary, {"format": "expectrail.seeded-check/v0", "route": "smoke.json", "ok": True, "variants": [
            {"variant": "layering/v1", "patch": "bugs/layering/v1.patch", "frames": 2, "framesDifferingFromClean": 2,
             "traceDiffersFromClean": True, "visible": True},
            {"variant": "sinking/v2", "patch": "bugs/sinking/v2.patch", "frames": 2, "framesDifferingFromClean": 2,
             "traceDiffersFromClean": True, "visible": True}]})


def unity_shaped(root: Path) -> adapters.Adapter:
    """A project laid out as Unity lays one out, with its own caches; there is no Unity runner here,
    so this adapter is only for the parts that never replay: the fixer, the briefing and the scan."""
    (root / "Assets" / "Scripts").mkdir(parents=True)
    (root / "Assets" / "Scripts" / "Player.cs").write_text("public class Player {\n    float speed = 4f;\n}\n")
    (root / "Library").mkdir()
    (root / "Library" / "ArtifactDB").write_text("cached import, never part of a fix\n")
    return adapters.Adapter(**{**adapters.GODOT.__dict__, "name": "unity-shaped", "engine": "unity",
                               "game_root": root, "ignore": adapters.UNITY_IGNORE, "editable": ("Assets/Scripts/**",),
                               "prompt_subject": "a Unity 6 2D game", "text_suffixes": adapters.UNITY_TEXT_SUFFIXES,
                               "log_name": "Player.log", "ticks_per_second": 50})


def unity_request(adapter: adapters.Adapter) -> dict:
    return {"format": "expectrail.repair-request/v0", "id": "rr-unity-shaped",
            "base": {"tree": adapter.tree_digest(), "patch": None}, "editable": list(adapter.editable),
            "failing": [{"spec": {"id": "player-moves", "instruction": "The player moves."},
                         "verdict": {"result": "fail", "reason": "it did not"}, "route": {"name": "walk", "ticks": 50}}],
            "budget": {"attempts": 1, "minutesPerAttempt": 1}}


class EngineParametersTest(unittest.TestCase):
    """The fixer, the briefing, the proposal and the export scan take the engine from its adapter;
    called without one they are the Godot code they were."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.unity = unity_shaped(self.root / "project")

    def tearDown(self):
        self.tmp.cleanup()

    def test_unity_s_text_suffixes_are_ready(self):
        self.assertEqual(adapters.UNITY_TEXT_SUFFIXES, {".cs", ".unity", ".prefab", ".asset", ".meta", ".asmdef",
                                                        ".inputactions", ".shader"})

    def test_the_fixer_copies_digests_and_diffs_the_adapter_s_project(self):
        from agents.fixer import _diff_worktree, build_muse_prompt, prepare_fixer_workspace, run_fixer

        request = unity_request(self.unity)
        fix = self.root / "fix.patch"
        fix.write_text("--- a/Assets/Scripts/Player.cs\n+++ b/Assets/Scripts/Player.cs\n@@ -1,3 +1,3 @@\n"
                       " public class Player {\n-    float speed = 4f;\n+    float speed = 5f;\n }\n")
        meta = run_fixer(request, self.root / "out", candidate_patch=fix, adapter=self.unity)
        self.assertEqual(meta["source"], "fixture")
        self.assertFalse((self.root / "out" / "fixer-work" / "Library").exists())
        self.assertIn("speed = 5f", (self.root / "out" / "fixer-work" / "Assets" / "Scripts" / "Player.cs").read_text())

        work = self.root / "work"
        prepare_fixer_workspace(request, work, adapter=self.unity)
        base = self.root / "base"
        prepare_fixer_workspace(request, base, adapter=self.unity)
        (work / "Library").mkdir()
        (work / "Library" / "ArtifactDB").write_text("rebuilt by the editor\n")
        (work / "Assets" / "Scripts" / "Player.cs").write_text("public class Player {\n    float speed = 6f;\n}\n")
        text = _diff_worktree(base, work, editable=["**"], ignore=self.unity.ignore)
        self.assertIn("Assets/Scripts/Player.cs", text)
        self.assertNotIn("Library", text)
        self.assertIn("Library/ArtifactDB", _diff_worktree(base, work, editable=["**"], ignore=()))

        with self.assertRaises(SystemExit):  # the base tree names the project as its adapter digests it
            prepare_fixer_workspace(request, self.root / "w2", game=REPO / "game" / "platformer", adapter=self.unity)
        prompt = build_muse_prompt(request, rr_relpath="repair-request.json", attempt=1, adapter=self.unity)
        self.assertTrue(prompt.startswith("You are fixing a Unity 6 2D game bug.\n"), prompt[:80])

    def test_the_briefing_names_the_project_its_physics_rate_and_its_log(self):
        from agents import escalation

        run = self.root / "run"
        (run / "frames").mkdir(parents=True)
        (run / "frames" / "f00000000.png").write_bytes(b"")
        (run / "godot.log").write_text("")
        (run / "Player.log").write_text("")
        route = self.root / "route.json"
        route.write_text("{}")
        request = unity_request(self.unity)
        files = escalation.report_files(run, route, self.unity)
        self.assertIn("bug-report/Player.log", files)
        self.assertNotIn("bug-report/godot.log", files)
        self.assertIn("bug-report/godot.log", escalation.report_files(run, route))
        prompt = escalation.report_prompt(request, files, 1, adapter=self.unity)
        self.assertIn("You are fixing a bug in a Unity 6 2D game.", prompt)
        self.assertIn("physics ticks, 50 a second", prompt)
        self.assertIn("The game's log from that run is bug-report/Player.log.", prompt)
        web = escalation.report_prompt(request, escalation.report_files(run, route, "web"), 1, adapter="web")
        self.assertIn("You are fixing a bug in a web checkout page.", web)
        self.assertNotIn("physics ticks", web)
        self.assertNotIn(".log", web)
        brief, stage = escalation.briefing(request, files, 2, True, adapter=self.unity)
        self.assertEqual(stage, "evidence")
        self.assertTrue(brief["prompt"].startswith("You are fixing a Unity 6 2D game bug."))

    def test_the_proposal_takes_the_game_root_and_editable_files_from_the_adapter(self):
        from agents.assurance import proposal as ap

        self.assertEqual(ap.GAME_ROOT, "game/platformer")
        self.assertEqual(ap.game_root("web"), "apps/checkout/site")
        with self.assertRaises(ap.ProposalError):  # outside the repository: no pull request could change it
            ap.game_root(self.unity)
        problems = ap.editable_problems(["apps/checkout/site/checkout/index.html", "apps/checkout/site/assets/x.svg",
                                         "README.md"], list(adapters.get("web").editable), "apps/checkout/site")
        self.assertEqual(len(problems), 2)
        self.assertIn("README.md is outside the game root apps/checkout/site/", problems)

    def test_the_export_scan_reads_each_project_s_text_files(self):
        from agents import export_scan

        self.assertEqual(export_scan.GAME_TEXT, {".tscn", ".tres", ".gd", ".godot", ".cfg", ".import"})
        page = export_scan._clean_page_lines()
        self.assertEqual(page, export_scan._clean_game_lines("web"))
        self.assertTrue(any("checkout" in line for line in page))
        unity = export_scan._clean_game_lines(self.unity)
        self.assertIn("float speed = 4f;", unity)
        self.assertNotIn("cached import, never part of a fix", unity)  # no text suffix


if __name__ == "__main__":
    unittest.main()
