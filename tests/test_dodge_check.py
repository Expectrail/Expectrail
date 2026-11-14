"""The outside trial selects one check per project. No game or model runs here."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from expectrail.contracts import load
from expectrail.gate.verify import evaluate, observations, run_gate
from tests.test_ci_gate import FakeReplay
from tools.dodge_play_area import region
from tools import outside_trial as trial


def judge(spec, positions, ground=None):
    rows = [{"tick": tick, "player": pos, "ground": ground, "view": [1, 0, 0, 1, 0, 0]}
            for tick, pos in enumerate(positions)]
    trace = {"physicsTicksPerSecond": 60, "rows": rows}
    return evaluate(spec, observations(trace, "0" * 64), trace=trace)


class DodgeCheckTest(unittest.TestCase):
    def setUp(self):
        projects = {p["name"]: p for p in trial.load_list()}
        self.kinematic = projects["kinematic-character"]
        self.dodge = projects["dodge-the-creeps"]

    def test_layout_selects_the_project_spec_and_keeps_the_default_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for project, expected in [(self.dodge, trial.REPO / "tests/outside/specs/dodge-play-area.json"),
                                      (self.kinematic, trial.SPEC)]:
                with self.subTest(project=project["name"]):
                    folder = root / "source" / project["path"]
                    folder.mkdir(parents=True)
                    (folder / "project.godot").touch()
                    checkout = trial.lay_out(project, root / "source", root / "work")
                    self.assertEqual([p.name for p in (checkout / "specs").iterdir()], [expected.name])
                    self.assertEqual((checkout / "specs" / expected.name).read_bytes(), expected.read_bytes())

    def test_change_expectations_and_the_kinematic_ground_check(self):
        for project, expected in [(self.dodge, {"broken": "reject", "harmless": "needs-review"}),
                                  (self.kinematic, {"broken": "reject", "harmless": "needs-review",
                                                    "invisible": "needs-review"})]:
            self.assertEqual({c["name"]: c["expect"] for c in project.get("changes", [])}, expected)
        spec = load(trial.SPEC, "test-spec")
        self.assertEqual(judge(spec, [[10, 50]] * 120, ground=70)["result"], "pass")
        self.assertEqual(judge(spec, [[10, 100]], ground=70)["result"], "fail")

    def test_kinematic_gate_verdicts_with_stand_in_replays_and_no_vision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source" / self.kinematic["path"]
            src.mkdir(parents=True)
            (src / "project.godot").touch()
            base = trial.lay_out(self.kinematic, root / "source", root / "base")
            head = trial.lay_out(self.kinematic, root / "source", root / "head")
            for change in self.kinematic["changes"]:
                with self.subTest(change=change["name"]):
                    bug = head / "project/BUG"    # FakeReplay's fall-through switch
                    if change["name"] == "broken":
                        bug.touch()
                    else:
                        bug.unlink(missing_ok=True)
                    doc = run_gate(repo=head, base=base, game="project", routes=["routes/*.json"],
                                   specs="specs", work=root / "work" / change["name"],
                                   out=root / "out" / change["name"], replay=FakeReplay(), rule="both")
                    self.assertEqual(doc["decision"], change["expect"])
                    after = doc["checks"][0]["observed"]["after"]
                    self.assertEqual(after["engine"], "fail" if bug.exists() else "pass")

    def test_region_reads_native_viewport_size_and_refuses_a_scaled_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project.godot"
            display = "[display]\nwindow/size/viewport_width=100\nwindow/size/viewport_height=200\n"
            project.write_text(display + "[other]\nwindow/size/viewport_width=1000\n")
            left, top, right, bottom = region(project)
            project.write_text(display.replace("=100", "=110").replace("=200", "=250"))
            self.assertEqual(region(project), [left, top, right + 10, bottom + 50])
            project.write_text(display + "window/size/window_width_override=50\n")
            with self.assertRaisesRegex(ValueError, "native size"):
                region(project)

    def test_dodge_origin_may_touch_each_edge_but_may_not_cross_it(self):
        spec = load(trial.REPO / self.dodge["spec"], "test-spec")
        # Native viewport of the pinned Dodge project. No ground in any row.
        w, h = 480, 720
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "project.godot"
            settings.write_text(f"[display]\nwindow/size/viewport_width={w}\nwindow/size/viewport_height={h}\n")
            self.assertEqual(spec["assertion"]["region"]["box"], region(settings))
        inside = [[0, 0], [w, 0], [w, h], [0, h], [w - 1, h - 1]]
        self.assertEqual(judge(spec, inside)["result"], "pass")
        for outside in ([-1, h / 2], [w + 1, h / 2], [w / 2, -1], [w / 2, h + 1]):
            with self.subTest(outside=outside):
                verdict = judge(spec, inside + [outside])
                self.assertEqual((verdict["result"], verdict["firstFrame"]), ("fail", len(inside)))
        self.assertEqual(judge(spec, [[0, 0], None])["result"], "needs-review")

    def test_spec_must_be_an_outside_spec_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "projects.json"
            for value in (None, "tests/outside/specs/../escape.json", "/tmp/spec.json",
                          "tests/outside/specs/missing.json"):
                with self.subTest(value=value):
                    doc = json.loads(trial.LIST.read_text())
                    next(p for p in doc["projects"] if p["name"] == self.dodge["name"])["spec"] = value
                    manifest.write_text(json.dumps(doc))
                    with self.assertRaises(trial.TrialError):
                        trial.load_list(manifest)

    def test_a_project_spec_cannot_follow_a_link(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(trial, "REPO", Path(tmp).resolve()):
            spec = trial.REPO / self.dodge["spec"]
            spec.parent.mkdir(parents=True)
            target = trial.REPO / "other.json"
            target.write_text("{}")
            spec.symlink_to(target)
            with self.assertRaisesRegex(trial.TrialError, "symbolic links"):
                trial.project_spec(self.dodge)
