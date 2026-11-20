"""The do-nothing control (#675, piece 1): a generated check that passes when its actor does nothing is dropped."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail.contracts import validate_v1
from expectrail.jit import assess, cli, do_nothing
from expectrail.jit import run as run_mod
from expectrail.jit.run import NO_CONTROL_GIVEN, generate
from tests.jit_fixtures import ALWAYS_PASSES, GOOD_CHECK, Case, JitGame, model

REPO = Path(__file__).resolve().parents[1]
PROFILE = REPO / "discovery" / "platformer.profile.json"
PROF = json.loads(PROFILE.read_text())
GAME = REPO / "game" / "platformer"

# Walking right for 40 ticks moves the player further right than not walking. A frozen player fails it.
WALKS = {"id": "walking-moves-right", "statement": "Walking right 40 ticks before jumping moves the player right.",
         "claimId": "player.jump", "class": "player",
         "operation": {"type": "relation", "signal": "player_dx_px", "comparator": "gt", "toleranceAbs": 0,
                       "left": "jump-w0-x2", "right": "jump-w40-x2"}}


class FrozenJitGame(JitGame):
    """JitGame, where a patch whose name starts ``jit-do-nothing-player`` freezes the player: it stays where it
    starts, on the floor, facing the same way, and fires nothing."""

    def __init__(self):
        super().__init__()
        self.patch_sets: list[list[str]] = []

    def __call__(self, route_path, run_dir, patches=()):
        names = [Path(p).stem for p in patches]
        self.patch_sets.append(names)
        frozen = any(n.startswith("jit-do-nothing-player") for n in names)
        rest = [p for p in patches if not Path(p).stem.startswith("jit-do-nothing-")]
        out = super().__call__(route_path, run_dir, patches=rest)
        if frozen:
            path = Path(run_dir) / "trace.json"
            trace = json.loads(path.read_text())
            first = trace["rows"][0]
            for row in trace["rows"]:
                row.update(player=list(first["player"]), onFloor=True, facing=first["facing"], projectiles=[])
            path.write_text(json.dumps(trace))
        return out


def _copy_game(dest: Path) -> Path:
    shutil.copytree(GAME, dest, ignore=shutil.ignore_patterns(".godot"))
    return dest


class Generator(unittest.TestCase):
    """The control is built from the check's class, the profile's selectors and the game's own files."""

    def test_bundled_game_controls(self):
        rows = {c["class"]: c for c in do_nothing.controls(GAME, PROF, do_nothing.CLASSES)}
        self.assertEqual(rows["player"]["mode"], "frozen")
        self.assertEqual(rows["player"]["files"], ["player/player.gd"])
        self.assertIn("+\treturn\n", rows["player"]["patchText"])
        self.assertEqual(rows["enemy"]["mode"], "frozen")
        self.assertEqual(rows["enemy"]["files"], ["enemy/enemy.gd"])
        # A bullet is made by the gun at run time, so it is never made: shoot returns false at once.
        self.assertEqual(rows["projectile"]["mode"], "never-made")
        self.assertEqual(rows["projectile"]["files"], ["player/gun.gd"])
        self.assertIn("+\treturn false\n", rows["projectile"]["patchText"])
        for row in rows.values():
            self.assertIsNone(row["reason"])

    def test_each_control_applies_to_the_clean_game_and_returns_first(self):
        from harness.run import apply_patches

        for row in do_nothing.controls(GAME, PROF, do_nothing.CLASSES):
            with self.subTest(cls=row["class"]), tempfile.TemporaryDirectory() as tmp:
                work = _copy_game(Path(tmp) / "g")
                patch = Path(tmp) / "c.patch"
                patch.write_text(row["patchText"])
                apply_patches(work, [patch])
                text = (work / row["files"][0]).read_text().splitlines()
                func = "func shoot(" if row["mode"] == "never-made" else "func _physics_process("
                at = next(i for i, line in enumerate(text) if line.startswith(func))
                self.assertIn(text[at + 1].strip(), ("return", "return false"))
                self.assertNotEqual((work / row["files"][0]).read_bytes(), (GAME / row["files"][0]).read_bytes())

    def test_same_game_same_bytes(self):
        one = do_nothing.controls(GAME, PROF, ["player", "enemy"])
        two = do_nothing.controls(GAME, PROF, ["enemy", "player", "enemy"])
        self.assertEqual(one, two)

    def _game(self, tmp: str) -> Path:
        return _copy_game(Path(tmp) / "g")

    def test_cannot_tell_is_a_reason_never_a_guess(self):
        cases = {}
        with tempfile.TemporaryDirectory() as tmp:
            game = self._game(tmp)
            cases["no selector"] = (game, dict(PROF, selectors={}), "player", "names no node")
        with tempfile.TemporaryDirectory() as tmp:
            game = self._game(tmp)
            (game / "enemy" / "enemy2.tscn").write_text((game / "enemy" / "enemy.tscn").read_text())
            self.assertIn("2 scenes", do_nothing.controls(game, PROF, ["enemy"])[0]["reason"])
        with tempfile.TemporaryDirectory() as tmp:
            game = self._game(tmp)
            gd = game / "enemy" / "enemy.gd"
            gd.write_text(gd.read_text().replace("func _physics_process(", "func walk_tick("))
            self.assertIn("defines none of", do_nothing.controls(game, PROF, ["enemy"])[0]["reason"])
        with tempfile.TemporaryDirectory() as tmp:
            game = self._game(tmp)
            gd = game / "player" / "gun.gd"
            gd.write_text(gd.read_text().replace("-> bool:", "-> Bullet:"))
            reason = do_nothing.controls(game, PROF, ["projectile"])[0]["reason"]
            self.assertIn("returns Bullet", reason)
        for name, (game, prof, cls, want) in cases.items():
            with self.subTest(name):
                row = do_nothing.controls(game, prof, [cls])[0]
                self.assertIsNone(row["patchText"])
                self.assertIn(want, row["reason"])

    def test_a_script_outside_the_game_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = self._game(tmp)
            scene = game / "enemy" / "enemy.tscn"
            scene.write_text(scene.read_text().replace('path="res://enemy/enemy.gd"', 'path="res://../outside.gd"'))
            (Path(tmp) / "outside.gd").write_text("extends Node\nfunc _process(d):\n\tpass\n")
            row = do_nothing.controls(game, PROF, ["enemy"])[0]
            self.assertIsNone(row["patchText"])
            self.assertIn("not a file in the game", row["reason"])


class Rule(unittest.TestCase):
    def test_outcomes(self):
        p, f = ["pass"] * 3, ["fail"] * 3
        self.assertEqual(assess.do_nothing(p), "passes")
        self.assertEqual(assess.do_nothing(f), "fails")
        self.assertEqual(assess.do_nothing([]), "not-run")
        for runs in (["pass", "pass"], ["pass", "fail"], ["not_exercised"], ["insufficient_observation"] * 3):
            with self.subTest(runs=runs):
                self.assertEqual(assess.do_nothing(runs), "indeterminate")

    def test_passing_the_control_makes_a_check_invalid_even_with_a_kill(self):
        v = assess.validity(["pass"] * 3, {"base": ["fail"] * 3}, do_nothing_runs=["pass"] * 3)
        self.assertFalse(v["valid"])
        self.assertEqual(v["reasons"], [assess.DO_NOTHING_PASSED])
        for runs in (["fail"] * 3, ["not_exercised"], [], None):
            with self.subTest(runs=runs):
                self.assertTrue(assess.validity(["pass"] * 3, {"base": ["fail"] * 3}, do_nothing_runs=runs)["valid"])


class Pipeline(unittest.TestCase):
    def _run(self, answer, game=None, **kw):
        case = Case()
        game = game or FrozenJitGame()
        intent, _ = model({"candidates": answer})
        doc = generate(PROFILE, "I can keep jumping in the air forever.", case.patch("fix-wrong"),
                       [case.patch("air-jump")], case.dir / "out", runner=game, intent=intent,
                       variants_fn=case.variants("variant-airjump"), **kw)
        validate_v1(doc, "jit-run")
        return doc, game, case

    def _controls(self, classes):
        return do_nothing.controls(GAME, PROF, classes)

    def test_a_check_that_passes_the_frozen_player_is_dropped_before_the_near_misses(self):
        doc, game, case = self._run([GOOD_CHECK, ALWAYS_PASSES, WALKS], do_nothing=self._controls)
        rows = {v["specId"]: v for v in doc["validity"]}
        self.assertEqual(doc["status"], "complete")
        self.assertEqual([c["class"] for c in doc["doNothing"]], ["player"])
        self.assertEqual(doc["doNothing"][0]["mode"], "frozen")
        # "No more air jumps from eight presses than from two" holds for a player that never moves.
        sid = "jit-no-extra-air-jumps"
        self.assertEqual(rows[sid]["doNothing"]["outcome"], "passes")
        self.assertEqual(rows[sid]["doNothing"]["runs"], ["pass"] * 3)
        self.assertFalse(rows[sid]["valid"])
        self.assertIn(assess.DO_NOTHING_PASSED, rows[sid]["reasons"])
        self.assertEqual(rows[sid]["variantResults"], {})
        self.assertEqual(rows[sid]["outcome"], "not-evaluated")
        # A rise check needs a jump to judge: on a frozen player it is not exercised, so this control cannot
        # drop it (it stops after the first run); the near-miss rule still does.
        always = rows["jit-always-passes"]
        self.assertEqual(always["doNothing"]["runs"], ["not_exercised"])
        self.assertEqual(always["doNothing"]["outcome"], "indeterminate")
        self.assertEqual(always["reasons"], ["killed no near-miss variant"])
        walks = rows["jit-walking-moves-right"]
        self.assertEqual(walks["doNothing"]["outcome"], "fails")
        self.assertEqual(walks["doNothing"]["runs"], ["fail"] * 3)
        self.assertNotIn(assess.DO_NOTHING_PASSED, walks["reasons"])
        self.assertIn("base", walks["variantResults"])
        self.assertEqual(doc["catches"], [])
        # The control is the clean game with only the control patch, saved beside the record.
        saved = case.dir / "out" / "jit-controls" / "jit-do-nothing-player.patch"
        self.assertEqual(run_mod._sha_bytes(saved.read_bytes()), doc["doNothing"][0]["patchSha256"])
        self.assertIn(["jit-do-nothing-player"], game.patch_sets)
        report = cli.render(doc)
        self.assertIn("Do-nothing controls (#675): player: frozen (player/player.gd)", report)
        self.assertIn("| passes (pass, pass, pass) |", report)

    def test_without_the_control_the_old_catch_stands_and_says_why(self):
        doc, _, _ = self._run([GOOD_CHECK])
        row = doc["validity"][0]
        self.assertTrue(row["valid"])
        self.assertEqual(row["doNothing"], {"control": None, "runs": [], "outcome": "not-run",
                                            "reason": NO_CONTROL_GIVEN})
        self.assertEqual(doc["doNothing"], [])
        self.assertEqual([c["specId"] for c in doc["catches"]], ["jit-no-extra-air-jumps"])

    def test_a_class_with_no_control_is_not_run_with_the_reason(self):
        none = lambda classes: [{"class": c, "id": f"do-nothing:{c}", "mode": None, "files": [], "patchText": None,  # noqa: E731
                                 "reason": "0 scenes have a root node named 'Player'"} for c in classes]
        doc, game, _ = self._run([GOOD_CHECK], do_nothing=none)
        row = doc["validity"][0]
        self.assertEqual(row["doNothing"]["outcome"], "not-run")
        self.assertIn("0 scenes", row["doNothing"]["reason"])
        self.assertTrue(row["valid"])
        self.assertIsNone(doc["doNothing"][0]["patchSha256"])
        self.assertFalse(any(n.startswith("jit-do-nothing") for s in game.patch_sets for n in s))

    def test_a_check_that_fails_the_reference_runs_no_control(self):
        miscalibrated = dict(ALWAYS_PASSES, id="never-rises", operation={"type": "max_episode_rise", "maxPx": 1})
        doc, game, _ = self._run([miscalibrated], do_nothing=self._controls)
        row = doc["validity"][0]
        self.assertEqual(row["doNothing"]["outcome"], "not-run")
        self.assertEqual(doc["doNothing"], [])
        self.assertFalse(any(n.startswith("jit-do-nothing") for s in game.patch_sets for n in s))

    def test_the_real_harness_makes_the_controls_from_the_game(self):
        game = FrozenJitGame()
        case = Case()
        intent, _ = model({"candidates": [GOOD_CHECK, WALKS]})
        with mock.patch.object(run_mod, "_default_runner", return_value=game):
            doc = generate(PROFILE, "I can keep jumping in the air forever.", case.patch("fix-wrong"),
                           [case.patch("air-jump")], case.dir / "out", intent=intent,
                           variants_fn=case.variants("variant-airjump"), game=GAME)
        rows = {v["specId"]: v for v in doc["validity"]}
        self.assertEqual(rows["jit-no-extra-air-jumps"]["doNothing"]["outcome"], "passes")
        self.assertEqual(rows["jit-walking-moves-right"]["doNothing"]["outcome"], "fails")
        made = do_nothing.controls(GAME, PROF, ["player"])[0]
        self.assertEqual(doc["doNothing"][0]["patchSha256"], run_mod._sha_bytes(made["patchText"].encode()))

    def test_false_turns_the_control_off(self):
        game = FrozenJitGame()
        case = Case()
        intent, _ = model({"candidates": [GOOD_CHECK]})
        with mock.patch.object(run_mod, "_default_runner", return_value=game):
            doc = generate(PROFILE, "r", case.patch("fix-wrong"), [case.patch("air-jump")], case.dir / "out",
                           intent=intent, variants_fn=case.variants("variant-airjump"), do_nothing=False)
        self.assertEqual(doc["validity"][0]["doNothing"]["reason"], NO_CONTROL_GIVEN)


if __name__ == "__main__":
    unittest.main()


class Revision(unittest.TestCase):
    def test_the_revision_is_told_the_check_passed_with_the_actor_doing_nothing(self):
        from expectrail.jit.intent import feedback

        entry = {"spec": {"id": "jit-a"}}
        row = {"specId": "jit-a", "valid": False, "reference": ["pass"] * 3, "killed": ["base"],
               "doNothing": {"control": "do-nothing:player", "runs": ["pass"] * 3, "outcome": "passes", "reason": None}}
        record = {"variants": [{"id": "base", "kind": "base"}], "validity": [row]}
        kept, rejected = feedback([entry], record)
        self.assertEqual(kept, [])
        self.assertEqual(rejected[0]["why"], "passed-with-the-actor-doing-nothing")
        row["doNothing"]["outcome"] = "fails"
        row["valid"] = True
        self.assertEqual(feedback([entry], record)[0], [entry])


class PublicMeasurement(unittest.TestCase):
    """tools/do_nothing_public.py: the public records' checks on the controls, with a stand-in engine."""

    def test_rows_counts_and_page(self):
        from tests.test_discovery import FakeGame
        from tools import do_nothing_public as tool

        fake = FakeGame()

        def runner(route, out, game=None, patches=(), capture_frames=False, ui_integers=False):
            fake(route, out, patches=[])
            return {"engine": {"version": "stand-in"}, "game": {"patchSha256": None}}

        with tempfile.TemporaryDirectory() as tmp:
            doc = tool.measure(Path(tmp) / "work", runner=runner)
            self.assertTrue((Path(tmp) / "work" / "rows.json").is_file())
            for cls in do_nothing.CLASSES:
                self.assertTrue((Path(tmp) / "work" / f"do-nothing-{cls}.patch").is_file())
        s = tool.summary(doc)
        self.assertEqual(s["checks"], 137)
        self.assertEqual(s["onReference"], 135)
        self.assertEqual(s["keptByOldRule"], 91)
        self.assertEqual(sum(s["onReferenceOutcomes"].values()), 135)
        # A model-proposed probe has no route in the library: those checks are not run, and say why.
        custom = [r for r in doc["rows"] if r["reason"] and r["reason"].startswith("route not in the probe library")]
        self.assertTrue(custom)
        self.assertTrue(all(r["outcome"] == "not-run" and r["runs"] == [] for r in custom))
        page = tool.markdown(doc, "stand-in")
        self.assertIn("Engine: stand-in.", page)
        # Three tables, each a header and a rule: three controls, three classes, 137 checks.
        self.assertEqual(page.count("\n| "), (2 + 3) + (2 + 3) + (2 + 137))

    def test_private_roots_are_refused(self):
        from tools import do_nothing_public as tool

        with tempfile.TemporaryDirectory() as tmp:
            for name in ("fresh-3", "Expectrail-heldout"):
                with self.subTest(name), self.assertRaises(ValueError):
                    tool.measure(Path(tmp) / f"w-{name}", records=Path(tmp) / name)
