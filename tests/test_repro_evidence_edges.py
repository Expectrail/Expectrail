"""Frames where an object is only partly on screen (#286): written into the evidence record from the clean
game's own record, checked by its reader, shown to the proposer under the pixel setting only, and named by
the judge when a window reaches one. A simulated game throughout; nothing starts the engine or asks a model."""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agents import template_observations as sensor
from expectrail.contracts import load_strict
from expectrail.jit import intent, offer, pixel
from expectrail.jit.probes import jit_library
from expectrail.repro import evidence
from tests.test_discovery import PROFILE
from tests.test_repro_bench import STUB
from tests.test_repro_screen import FRAMES, H, W, Drawn

PROBES = ("hold-right", "jump-w0-x8")
NONE = {"enemy": None, "bullet": None}

# One enemy box a frame (frame pixels; the simulated game's camera is the identity). The frame is W x H = 12 x 6.
#   0: wholly on screen.  1, 2: past the left edge.  3: wholly off screen.  4: past the right edge.
ENEMY = {0: [2.0, 1.0, 5.0, 4.0], 1: [-2.0, 1.0, 3.0, 4.0], 2: [-1.0, 1.0, 2.0, 4.0], 3: [-10.0, 1.0, -5.0, 4.0],
         4: [10.0, 1.0, 14.0, 4.0]}
WANT_ENEMY = {"frames": 3, "spans": [[1, 2], [4, 4]]}


class Edged(Drawn):
    """Drawn, whose record logs object boxes: the enemy of ENEMY on the tick each frame reads, no bullet.
    ``drift`` moves the enemy of frame 0 past the edge on the first clean replay of that probe only."""

    def __init__(self, drift=None, boxes=True):
        super().__init__()
        self.drift, self.boxes, self.calls = drift, boxes, {}

    def __call__(self, route_path, run_dir, patches=()):
        super().__call__(route_path, run_dir, patches=patches)
        name = json.loads(Path(route_path).read_text())["name"]
        n = self.calls[name] = self.calls.get(name, 0) + (0 if patches else 1)
        path = Path(run_dir) / "trace.json"
        trace = json.loads(path.read_text())
        trace["capabilities"]["objectBoxes"] = self.boxes
        step = trace["physicsTicksPerSecond"] // 60
        frame_of = {(i + 1) * step - 1: i for i in range(FRAMES)}
        for row in trace["rows"]:
            box = ENEMY.get(frame_of.get(row["tick"], 0))
            if self.drift == name and n == 1 and frame_of.get(row["tick"]) == 0:
                box = [-1.0, 1.0, 2.0, 4.0]
            row["enemyBoxes"] = [[1, *box]]
            row["projectileBoxes"] = []
        path.write_text(json.dumps(trace))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-evidence-edges-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.patch = self.tmp / "sprite-flip.patch"
        self.patch.write_text(STUB)
        self.profile = load_strict(PROFILE, "mechanics-profile")
        self.probes = [p for p in jit_library(self.profile["actions"]) if p["id"] in PROBES]

    def make(self, game, out="out"):
        return evidence.evidence(self.profile, self.probes, [self.patch], self.tmp / out, runner=game)

    @staticmethod
    def rows(record):
        return {r["probe"]: r for r in record["rows"]}


class Written(Base):
    def test_each_kind_gets_the_frames_it_is_partly_on_screen_as_runs(self):
        record = self.make(Edged())
        for pid in PROBES:
            edges = self.rows(record)[pid]["edges"]
            self.assertEqual(edges, {"of": FRAMES, "objects": {"enemy": WANT_ENEMY, "bullet": {"frames": 0, "spans": []}}})
        self.assertEqual(evidence.load(self.tmp / "out" / evidence.NAME), record)

    def test_a_record_that_logs_no_object_boxes_cannot_say(self):
        for game in (Drawn(), Edged(boxes=False)):
            with self.subTest(game=type(game).__name__):
                record = self.make(game, out=f"out-{id(game)}")
                self.assertEqual({r["edges"]["objects"] == NONE for r in record["rows"]}, {True})

    def test_two_clean_replays_that_disagree_cannot_say_for_that_probe(self):
        rows = self.rows(self.make(Edged(drift="hold-right")))
        self.assertIsNone(rows["hold-right"]["edges"]["objects"]["enemy"])
        self.assertEqual(rows["hold-right"]["edges"]["objects"]["bullet"], {"frames": 0, "spans": []})
        self.assertEqual(rows["jump-w0-x8"]["edges"]["objects"]["enemy"], WANT_ENEMY)

    def test_the_bug_build_does_not_decide_them(self):
        # The bug build moves the enemy nowhere here, and a bug build that did would not change the clean game's.
        class BugMoves(Edged):
            def __call__(self, route_path, run_dir, patches=()):
                super().__call__(route_path, run_dir, patches=patches)
                if patches:
                    path = Path(run_dir) / "trace.json"
                    trace = json.loads(path.read_text())
                    for row in trace["rows"]:
                        row["enemyBoxes"] = [[1, -1.0, 1.0, 2.0, 4.0]]
                    path.write_text(json.dumps(trace))

        rows = self.rows(self.make(BugMoves()))
        self.assertEqual(rows["hold-right"]["edges"]["objects"]["enemy"], WANT_ENEMY)

    def test_more_runs_than_the_bound_are_closed_up_so_none_is_left_out(self):
        frames = list(range(0, 2 * (evidence.MAX_EDGE_SPANS + 6), 2))
        spans = evidence._spans(frames)
        self.assertEqual(len(spans), evidence.MAX_EDGE_SPANS)
        self.assertEqual(spans[-1], [frames[evidence.MAX_EDGE_SPANS - 1], frames[-1]])
        held = {n for a, b in spans for n in range(a, b + 1)}
        self.assertTrue(set(frames) <= held)
        self.assertEqual(evidence._spans([3, 4, 5, 9]), [[3, 5], [9, 9]])
        self.assertEqual(evidence._spans([]), [])

    def test_it_agrees_with_what_the_sensor_refuses_to_judge(self):
        # A box is an edge frame exactly when the no-model sensor neither counts it outside nor looks at it.
        class Image:
            width, height = W, H

        class Nothing:   # a matcher that finds nothing: only reached for a box wholly on screen
            @staticmethod
            def match(_image, _box):
                return None, None

        trace = {"physicsTicksPerSecond": 120, "capabilities": {"objectBoxes": True}, "ticks": 2,
                 "rows": [{"tick": t, "view": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0], "enemyBoxes": []} for t in range(2)]}
        boxes = [[x, y, x + 3.0, y + 3.0] for x in (-4.0, -3.0, -1.0, 0.0, 4.0, 9.0, 10.0, 12.0)
                 for y in (-3.0, -1.0, 0.0, 2.0, 3.0, 5.0, 6.0)]
        for box in boxes:
            trace["rows"][1]["enemyBoxes"] = [[1, *box]]
            where = sensor.object_predictions(trace, [0], "enemy", 60)[0]
            outside = box[2] <= 0 or box[3] <= 0 or box[0] >= W or box[1] >= H   # template_observer._look_named
            refused = not outside and sensor.look(Nothing(), Image(), where[0][1], {}, False)["status"] == "out-of-frame"
            with self.subTest(box=box):
                run = self.tmp / f"r{boxes.index(box)}"
                run.mkdir()
                (run / "trace.json").write_text(json.dumps(trace))
                (run / "replay.json").write_text(json.dumps({"capture": {"fps": 60}}))
                got = evidence.edge_frames(run, 1, {"width": W, "height": H})["enemy"]
                self.assertEqual(got["frames"] == 1, refused)


class Read(Base):
    def setUp(self):
        super().setUp()
        self.record = self.make(Edged())

    def refused(self, change, word):
        bad = copy.deepcopy(self.record)
        change(bad["rows"][0])
        found = evidence.problems(bad)
        self.assertTrue(any(word in f for f in found), found)

    def test_runs_that_do_not_agree_with_themselves_are_refused(self):
        def enemy(value):
            return lambda r: r["edges"]["objects"].__setitem__("enemy", value)

        partly = "partly on screen"
        self.refused(enemy({"frames": 3, "spans": [[1, 2], [3, 3]]}), partly)       # touching
        self.refused(enemy({"frames": 3, "spans": [[4, 4], [1, 2]]}), partly)       # out of order
        self.refused(enemy({"frames": 2, "spans": [[1, 2], [4, 4]]}), partly)       # fewer than held, under the bound
        self.refused(enemy({"frames": 4, "spans": [[1, 2], [4, 4]]}), partly)       # more than held
        self.refused(enemy({"frames": 1, "spans": [[5, 5]]}), partly)               # past the last frame
        self.refused(enemy({"frames": 1, "spans": [[2, 1]]}), partly)               # backwards
        self.refused(enemy({"frames": 0, "spans": [[1, 1]]}), partly)
        self.refused(lambda r: r["edges"]["objects"].__setitem__("coin", None), "edges")       # a kind not named
        self.refused(lambda r: r["edges"]["objects"].pop("bullet"), "edges")
        self.refused(lambda r: r["edges"]["objects"]["enemy"]["spans"].extend([[9, 9]] * 30), "spans")

    def test_closed_up_runs_may_hold_more_frames_than_counted(self):
        frames = list(range(0, 60, 2))
        spans = evidence._spans(frames)
        good = copy.deepcopy(self.record)
        good["rows"][0]["edges"] = {"of": 60, "objects": {"enemy": {"frames": len(frames), "spans": spans}, "bullet": None}}
        if good["rows"][0]["screen"]:
            good["rows"][0]["screen"]["of"] = 60
            good["rows"][0]["screen"]["frames"] = min(good["rows"][0]["screen"]["frames"], 60)
        self.assertEqual([f for f in evidence.problems(good) if "partly" in f], [])

    def test_an_error_row_carries_none_and_a_record_without_them_still_reads(self):
        def to_error(r):
            r.update(sees="error", record=None, screen=None, observer=None, error="boom")

        bad = copy.deepcopy(self.record)
        to_error(bad["rows"][0])
        bad["totals"] = evidence.totals(bad["rows"])
        self.assertTrue(any("an error row carries a reason and nothing else" in f for f in evidence.problems(bad)))
        old = copy.deepcopy(self.record)
        for r in old["rows"]:
            del r["edges"]
        self.assertEqual(evidence.problems(old), [])
        example = json.loads((evidence.REPO / "contracts" / "examples" / "repro-evidence.json").read_text())
        self.assertEqual(evidence.problems(example), [])


class TheExample(unittest.TestCase):
    def test_the_example_is_a_real_record_of_the_enemy_probes_and_reads(self):
        # Made on Godot 4.7.2 here, November 16: --defect enemy-walks-backwards on hold-right, reverse and
        # move-fire-right. The enemies enter at the screen's edge, so every probe has frames to avoid.
        path = evidence.REPO / "contracts" / "examples" / "repro-evidence-edges.json"
        record = evidence.load(path)
        edges = {r["probe"]: r["edges"]["objects"]["enemy"]["spans"] for r in record["rows"]}
        self.assertEqual(edges, {"hold-right": [[0, 15], [17, 27]], "move-fire-right": [[0, 15], [17, 27]],
                                 "reverse": [[0, 15], [17, 27], [87, 96], [98, 112], [114, 124]]})


class Shown(Base):
    def setUp(self):
        super().setUp()
        self.record = self.make(Edged())
        self.path = self.tmp / "out" / evidence.NAME

    def test_the_summary_carries_them_for_the_probes_it_shows(self):
        summary = evidence.for_proposer(self.record, probes=list(PROBES))
        self.assertTrue(summary["probes"])
        for entry in summary["probes"]:
            self.assertEqual(entry["partlyOnScreen"], {"enemy": [[1, 2], [4, 4]], "bullet": []})

    def test_a_kind_the_record_cannot_say_about_is_left_out(self):
        rows = self.rows(self.make(Edged(drift="hold-right"), out="drift"))
        record = evidence.load(self.tmp / "drift" / evidence.NAME)
        self.assertIsNone(rows["hold-right"]["edges"]["objects"]["enemy"])
        shown = {e["probe"]: e for e in evidence.for_proposer(record, probes=list(PROBES))["probes"]}
        self.assertEqual(shown["hold-right"]["partlyOnScreen"], {"bullet": []})

    def attached(self, setting):
        library = [p for p in offer.library(self.profile["actions"], setting, "report") if p["id"] in PROBES]
        notes = offer.attach_evidence(library, self.path, [self.patch], setting)
        self.assertEqual(notes, [])
        return library

    def test_under_the_pixel_setting_only_they_reach_the_prompt(self):
        px = self.attached(offer.PIXEL)
        self.assertEqual({json.dumps(p["differs"]["partlyOnScreen"], sort_keys=True) for p in px if "differs" in p},
                         {json.dumps({"bullet": [], "enemy": [[1, 2], [4, 4]]}, sort_keys=True)})
        sent = json.loads(intent.prompt("report", "", {}, self.profile, px, offer=offer.PIXEL,
                                        candidate=intent.WITHHELD, observer="visual-sensor"))["probesAvailable"]
        self.assertEqual({json.dumps(p["differs"].get("partlyOnScreen"), sort_keys=True) for p in sent if "differs" in p},
                         {json.dumps({"enemy": [[1, 2], [4, 4]], "bullet": []}, sort_keys=True)})
        ev = self.attached(offer.EVIDENCE)
        self.assertTrue(any("differs" in p for p in ev))
        self.assertTrue(all("partlyOnScreen" not in p.get("differs", {}) for p in ev))
        sent = json.loads(intent.prompt("report", "", {}, self.profile, ev, offer=offer.EVIDENCE,
                                        candidate=intent.WITHHELD))["probesAvailable"]
        self.assertTrue(all("partlyOnScreen" not in p.get("differs", {}) for p in sent))

    def test_the_pixel_text_says_what_they_are_and_names_faces_motion(self):
        system = intent.system_for(offer.PIXEL)
        self.assertIn('"partlyOnScreen"', system)
        self.assertIn('{"type": "faces-motion"}', system)
        self.assertNotIn("partlyOnScreen", intent.system_for(offer.EVIDENCE))


class Judged(unittest.TestCase):
    def check(self, predicate):
        return {"id": "enemy-faces", "statement": "s", "object": "enemy", "observer": "visual-sensor",
                "probe": "hold-right", "predicate": predicate}

    def test_a_box_partly_off_screen_is_a_gap_that_says_so(self):
        partly = {"id": 3, "status": "out-of-frame", "promptBox": [-2.0, 1.0, 3.0, 4.0], "score": None, "box": None,
                  "error": "out-of-frame: predicted crop is not entirely on screen"}
        failed = {"id": 4, "status": "unavailable", "promptBox": None, "score": None, "box": None, "error": "x"}
        run = {"objects": {"enemy": [{"frame": 0, "asked": True, "boxes": [partly, failed], "outside": 0}]},
               "facing": ["enemy"]}
        for predicate in ({"type": "visible", "minFraction": 1.0, "minScore": 0.5}, {"type": "faces-motion"}):
            with self.subTest(predicate=predicate["type"]):
                _per, gaps = pixel.named_observations(self.check(predicate), run)
                self.assertEqual([g["why"] for g in gaps],
                                 ["enemy 3 is partly off screen, and the observer judges only an object it sees whole",
                                  "the observer gave no answer for enemy 4"])


if __name__ == "__main__":
    unittest.main()
