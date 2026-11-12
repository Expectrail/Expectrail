"""Which surface the harness calls the ground under the player (#348).

The harness asks for the highest solid surface under the player's centre and under its two edges,
because a body rests on the highest point beneath it. Until November 12, 2026 the edges were always
the bundled robot's, 20 px either side. Godot's kinematic character demo has a player 14 px wide:
standing on the floor 20 px from a step it had a column inside the step, the step's top was read as
its ground, and the clean game was rejected (#263). The edges are now the player's own.

Two things are held, each with the real engine:
- `tests/projects/stepped-ground`, a level built in code (a floor with its top at y = 320, a gap
  from x = 192 to 256, a 64 px step from x = 448 to 512 with its top at 256) and a body 24 px wide
  moved along it: the ground changes where that body's own edge crosses, not 20 px out.
- the bundled game on `tests/routes/slope.json`, which walks up the level's slope: the robot's feet
  stay within 2 px of the logged ground all the way up, as on main. (The merge guard's first review
  of #349 found that a centre-column-first rule, the first attempt at this fix, read the ground up
  to 23.7 px low there.)

CI sets EXPECTRAIL_ENGINE_TESTS=required in `capture-smoke`, so a skip there is a failure.
Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from harness import run as hr

REPO = Path(__file__).resolve().parent.parent
PROJECT = REPO / "tests" / "projects" / "stepped-ground"
SCRIPT = REPO / "harness" / "godot" / "expectrail_harness.gd"
REQUIRED = os.environ.get("EXPECTRAIL_ENGINE_TESTS") == "required"


def real_godot() -> Path:
    named = os.environ.get("EXPECTRAIL_GODOT")
    found = [Path(named)] if named else sorted((REPO / "tools" / "godot").glob("Godot_v*"))
    found = [p for p in found if p.is_file()]
    if not found:
        if REQUIRED:
            raise AssertionError("this job must have Godot: run harness/get_godot.sh first")
        raise unittest.SkipTest("Godot is not downloaded (harness/get_godot.sh)")
    return found[0]


FEET = 13.25    # the bundled robot's feet below its origin (agents/observations.py FEET_OFFSET)


class ScriptTest(unittest.TestCase):
    def test_the_three_columns_are_asked_and_the_edges_are_the_players_own(self):
        code = SCRIPT.read_text(encoding="utf-8")
        body = code[code.index("func _ground_under("):code.index("func _edge_reach(")]
        self.assertIn("var reach := _edge_reach(_player)", body)
        self.assertIn("for dx in [-reach, 0.0, reach]:", body)
        self.assertNotIn("return centre", body)             # the first attempt: the centre alone when it has a surface
        self.assertNotIn("BODY_HALF_WIDTH", body)            # the constant is the fallback inside _edge_reach only
        # The bundled robot's shape is 42.5 px wide: its reach is the 20 px it always was.
        inset = float(re.search(r"^const EDGE_INSET := ([\d.]+)$", code, re.M).group(1))
        fallback = float(re.search(r"^const BODY_HALF_WIDTH := ([\d.]+)$", code, re.M).group(1))
        self.assertEqual(42.5 / 2 - inset, fallback)


class GroundUnderTest(unittest.TestCase):
    """A body 24 px wide: its reach is 12 - 1.25 = 10.75 px either side of its origin."""

    @classmethod
    def setUpClass(cls):
        godot = real_godot()
        cls.tmp = Path(tempfile.mkdtemp(prefix="expectrail-ground-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        hr.run(PROJECT / "routes" / "walk.json", cls.tmp / "run", game=PROJECT / "project", godot=godot,
               capture_frames=False)
        trace = json.loads((cls.tmp / "run" / "trace.json").read_text(encoding="utf-8"))
        cls.ground = {row["player"][0]: row.get("ground") for row in trace["rows"]}   # by the player's x

    def at(self, lo: float, hi: float) -> set:
        return {g for x, g in self.ground.items() if lo <= x < hi}

    def test_the_body_was_moved_along_the_whole_level(self):
        self.assertEqual((min(self.ground), max(self.ground)), (102.0, 530.0))

    def test_the_step_is_the_ground_only_once_the_bodys_own_edge_is_over_it(self):
        # The step is x 448 to 512. This body's right edge column reaches it at x = 438 (437.25),
        # and its left edge column leaves it after x = 522 (522.75). With the robot's 20 px the
        # step was the ground from x = 428, where a body this wide is 8 px short of touching it.
        self.assertEqual(self.at(246, 438), {320.0})
        self.assertEqual(self.at(438, 524), {256.0})
        self.assertEqual(self.at(524, 531), {320.0})

    def test_a_body_half_off_a_ledge_is_still_measured_against_the_ledge(self):
        # x 512 to 522: the centre is past the step and over the floor 64 px below; the left edge is
        # still on the step, and the step is the ground. (A centre-first rule said 320 here.)
        self.assertEqual(self.at(512, 524), {256.0})
        # The same at the gap's edges: the floor is the ground while an edge is still over it.
        self.assertEqual(self.at(192, 204), {320.0})
        self.assertEqual(self.at(246, 256), {320.0})

    def test_with_nothing_under_the_body_there_is_no_ground(self):
        # The gap is x 192 to 256; between x = 204 and 244 neither edge nor the centre is over a tile.
        self.assertEqual(self.at(204, 246), {None})


class SlopeTest(unittest.TestCase):
    """The bundled game, walked up its level's slope (x 838 to 896, y 640 up to 583)."""

    @classmethod
    def setUpClass(cls):
        godot = real_godot()
        cls.tmp = Path(tempfile.mkdtemp(prefix="expectrail-slope-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        hr.run(REPO / "tests" / "routes" / "slope.json", cls.tmp / "run", godot=godot, capture_frames=False)
        cls.rows = json.loads((cls.tmp / "run" / "trace.json").read_text(encoding="utf-8"))["rows"]

    def test_the_robot_reaches_the_slope_and_stops_on_it(self):
        last = self.rows[-1]
        self.assertTrue(838 < last["player"][0] < 896, last["player"])
        self.assertLess(last["player"][1], 600)      # well above the flat ground's 650 - 13.25
        self.assertTrue(last["onFloor"])

    def test_on_the_slope_the_feet_stay_on_the_logged_ground(self):
        on_slope = [r for r in self.rows if r.get("onFloor") and r["player"][0] >= 817]
        self.assertGreater(len(on_slope), 100)
        gaps = [(r["player"][1] + FEET) - r["ground"] for r in on_slope]
        # Main's harness: -1.38 to -1.15 over these rows. A centre-first rule: -25.0 to -5.7.
        self.assertGreaterEqual(min(gaps), -2.0, min(gaps))
        self.assertLessEqual(max(gaps), 0.0, max(gaps))


if __name__ == "__main__":
    unittest.main()
