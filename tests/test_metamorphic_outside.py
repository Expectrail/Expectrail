"""Mirror-inputs metamorphic checks on an outside game (#675, piece 3, slice 3).

No outside project is fetched or started here. The real run is the `metamorphic-outside` job of
`outside-trial.yml`; these tests use a small project of their own and the outside list as committed.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import patching
from tools import metamorphic_outside as mo
from tools import outside_trial

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "outside-trial.yml"

PROJECT_GODOT = """config_version=5

[application]

config/name="Fake"

[input]

move_left={"deadzone": 0.5, "events": []}
move_right={"deadzone": 0.5, "events": []}
jump={"deadzone": 0.5, "events": []}
"""
SCENE = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://player/player.gd" id="1"]

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1")
"""
SCRIPT = """extends CharacterBody2D

func _physics_process(delta):
\tmove_and_slide()
"""


def fake_game(root: Path, project: str = PROJECT_GODOT, player: bool = True) -> Path:
    game = root / "game"
    (game / "player").mkdir(parents=True)
    (game / "project.godot").write_text(project, encoding="utf-8")
    if player:
        (game / "player" / "player.tscn").write_text(SCENE, encoding="utf-8")
        (game / "player" / "player.gd").write_text(SCRIPT, encoding="utf-8")
    return game


def kinematic() -> dict:
    return next(p for p in outside_trial.load_list() if p["name"] == "kinematic-character")


class Seed(unittest.TestCase):
    def applied(self, project: str) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        game = fake_game(tmp, project)
        patch = tmp / "seed.patch"
        patch.write_text(mo.seed_patch(game), encoding="utf-8")
        patching.apply(game, patch)
        return game

    def test_the_seed_adds_an_autoload_to_a_project_without_one(self):
        game = self.applied(PROJECT_GODOT)
        text = (game / "project.godot").read_text()
        self.assertTrue(text.startswith(PROJECT_GODOT))
        self.assertIn('\n[autoload]\n\nExpectrailSeedDragLeft="*res://expectrail_seed_drag_left.gd"\n', text)
        self.assertEqual((game / mo.SEED_FILE).read_text(), mo.seed_script())

    def test_the_seed_joins_an_autoload_section_already_there(self):
        game = self.applied(PROJECT_GODOT + '\n[autoload]\n\nGlobal="*res://global.gd"\n')
        text = (game / "project.godot").read_text()
        self.assertEqual(text.count("[autoload]"), 1)
        self.assertLess(text.index("ExpectrailSeedDragLeft"), text.index("Global="))

    def test_the_seed_applies_to_a_project_file_with_no_final_newline(self):
        game = self.applied(PROJECT_GODOT.rstrip("\n"))
        text = (game / "project.godot").read_text()
        self.assertIn('jump={"deadzone": 0.5, "events": []}\n\n[autoload]\n', text)

    def test_the_seed_pushes_back_only_while_move_left_is_held(self):
        script = mo.seed_script()
        self.assertIn('if not Input.is_action_pressed("move_left"):\n\t\treturn', script)
        self.assertIn("player.position.x += 1.0", script)
        self.assertNotIn("move_right", script)

    def test_a_project_that_already_has_the_seed_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = fake_game(Path(tmp))
            (game / mo.SEED_FILE).write_text("")
            with self.assertRaisesRegex(mo.OutsideError, "already exists"):
                mo.seed_patch(game)


class Catalog(unittest.TestCase):
    def test_the_actions_are_the_projects_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(mo.catalog(fake_game(Path(tmp))), ["jump", "move_left", "move_right"])

    def test_a_project_with_no_input_action_is_refused_not_given_a_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = fake_game(Path(tmp), "config_version=5\n")
            with self.assertRaisesRegex(mo.OutsideError, "no input action"):
                mo.catalog(game)


class Builds(unittest.TestCase):
    def test_the_plan_for_kinematic_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plan, notes = mo.builds(fake_game(tmp), kinematic(), tmp)
        self.assertEqual(notes, [])
        self.assertEqual([(b["id"], b["kind"], b["reps"]) for b in plan],
                         [("clean", "clean", 3), ("do-nothing", "control", 3), ("broken", "defect", 1),
                          ("harmless", "harmless", 1), ("invisible", "harmless", 1), ("drag-left", "defect", 1)])
        self.assertEqual(plan[1]["mode"], "frozen")
        self.assertEqual(plan[2]["patches"], [REPO / "tests/outside/kinematic-character/changes/broken.patch"])

    def test_no_player_scene_means_no_control_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plan, notes = mo.builds(fake_game(tmp, player=False), {"changes": []}, tmp)
        self.assertEqual([b["id"] for b in plan], ["clean", "drag-left"])
        self.assertEqual(notes[0]["build"], "do-nothing")
        self.assertTrue(notes[0]["reason"].startswith("cannot tell: "))

    def test_a_change_patch_outside_the_repository_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with self.assertRaises(outside_trial.TrialError):
                mo.builds(fake_game(tmp), {"changes": [{"name": "x", "patch": "../x.patch", "expect": "reject"}]}, tmp)


def fake_replays(work, game, routes, plan, runner=None, workers=2, resume=False, sandbox=None):
    eps = {(b["id"], pid): [{"build": b["id"], "samples": [], "events": []} for _ in range(b["reps"])]
           for b in plan for pid in routes}
    evidence = {f"{b['id']}/{pid}": {"traces": ["t"] * b["reps"], "engine": "4.7.2.stable"} for b in plan for pid in routes}
    fake_replays.sandbox = sandbox
    return {"episodes": eps, "evidence": evidence}


def fake_evaluate(entry, ids, eps):
    build = eps[ids[0]]["build"]
    signal = entry["spec"]["operation"]["signal"]
    if build == "do-nothing":
        return "not_exercised"
    if build == "drag-left" and signal == "player_dx_px":
        return "fail"
    if build == "invisible" and signal == "air_jumps":
        return "fail"
    return "pass"


class Measure(unittest.TestCase):
    def measured(self) -> dict:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        with mock.patch.object(mo.public, "replay_all", fake_replays), \
                mock.patch("expectrail.jit.run._evaluate", fake_evaluate):
            return mo.measure(fake_game(tmp), kinematic(), tmp / "work")

    def test_catches_and_false_rejects_are_counted_apart(self):
        doc = self.measured()
        s = mo.summary(doc)
        self.assertEqual(fake_replays.sandbox, "require")
        self.assertEqual(s["kept"], s["checks"])
        self.assertEqual(len(s["catches"]["drag-left"]), s["pairs"])
        self.assertEqual(s["catches"]["broken"], [])
        self.assertEqual(s["falseRejects"]["harmless"], [])
        self.assertEqual(len(s["falseRejects"]["invisible"]), s["pairs"])
        self.assertTrue(all(r["falseRejects"] == ["invisible"] for r in doc["rows"] if r["signal"] == "air_jumps"))

    def test_the_markdown_names_the_project_and_each_change(self):
        doc = self.measured()
        text = mo.markdown(doc)
        self.assertIn("commit `b761b4cd5718a7118f2c95eb55f181d0a5f004f1`", text)
        self.assertIn(f"**{mo.summary(doc)['checks'] // 4} kept checks catch it**", text)
        self.assertIn("`invisible` (harmless", text)
        self.assertIn("fail it (false rejects)", text)
        self.assertIn("Sandbox: `require`", text)

    def test_the_markdown_says_what_the_counts_cannot_say(self):
        # Sean's review of #719: the never-exercised checks, the silent control and the seeded fault are
        # stated in the measurement itself, not left for a reader to find in the table.
        def evaluate(entry, ids, eps):
            build = eps[ids[0]]["build"]
            signal = entry["spec"]["operation"]["signal"]
            if build == "do-nothing" or signal in ("max_rise_px", "air_jumps"):
                return "not_exercised"
            return "fail" if build == "drag-left" and signal == "player_dx_px" else "pass"

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        with mock.patch.object(mo.public, "replay_all", fake_replays), \
                mock.patch("expectrail.jit.run._evaluate", evaluate):
            doc = mo.measure(fake_game(tmp), kinematic(), tmp / "work")
        s = mo.summary(doc)
        half = s["checks"] // 2
        self.assertEqual(len(s["neverExercised"]), half)
        self.assertEqual(s["controlSilent"], s["kept"])
        self.assertEqual(s["seededCatching"], ["drag-left"])
        text = mo.markdown(doc)
        self.assertIn("## What these counts can and cannot say", text)
        self.assertIn(f"**{half} of {s['checks']} checks are not exercised on any build**", text)
        self.assertIn("`max_rise_px`, `air_jumps`", text)
        self.assertIn(f"**{s['kept']} of {s['kept']} kept checks are indeterminate on the do-nothing control**", text)
        self.assertIn("the control could not judge them, not that it cleared them", text)
        self.assertIn("direction-dependent", text)
        self.assertIn("`drag-left` was written for this measurement", text)
        self.assertIn("No declared defect is caught", text)

    def test_the_limits_are_quiet_when_they_do_not_apply(self):
        doc = self.measured()
        s = mo.summary(doc)
        self.assertEqual(s["neverExercised"], [])
        text = mo.markdown(doc)
        self.assertNotIn("not exercised on any build", text)
        self.assertIn("direction-dependent", text)

    def test_the_work_folder_must_be_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "work").mkdir()
            with self.assertRaises(FileExistsError):
                mo.measure(fake_game(tmp), kinematic(), tmp / "work")

    def test_an_unknown_project_exits_5(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(mo.main(["--source", tmp, "--out", str(Path(tmp) / "out"), "--project", "nope"]), 5)


class Workflow(unittest.TestCase):
    def test_the_job_fetches_kinematic_character_in_the_sandbox_with_no_secret(self):
        text = WORKFLOW.read_text()
        job = text[text.index("  metamorphic-outside:"):]
        self.assertIn("python -m tools.metamorphic_outside --fetch --workers 4 --out runs/metamorphic-outside", job)
        self.assertIn("bubblewrap", job)
        for word in ("secrets.", "environment:", "pull_request_target", "id-token", "permissions:"):
            self.assertNotIn(word, job)
        self.assertIn("permissions:\n  contents: read\n", text)
        self.assertIn("- 'tools/metamorphic_outside.py'", text)

    def test_the_tool_requires_the_sandbox_by_default(self):
        import inspect

        self.assertIn('default="require"', inspect.getsource(mo.main))


if __name__ == "__main__":
    unittest.main()
