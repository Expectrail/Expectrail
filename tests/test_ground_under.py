"""Which surface the harness calls the ground under the player (#348).

`tests/projects/stepped-ground` is a level built in code: a floor with its top at y = 320, a gap
from x = 192 to 256, and a 64 px step from x = 448 to 512 with its top at 256. A marker walks right
at a fixed height, 8 px above the floor. Until November 12, 2026 the harness took the highest
surface under the body's centre and its two edges (20 px either side), so 20 px before the step the
ground became the step's top and a player standing on the floor was reported 56 px below its
ground. Godot's kinematic character demo, unchanged, was rejected that way (#263).

The engine test runs where Godot is; CI sets EXPECTRAIL_ENGINE_TESTS=required in `capture-smoke`,
so a skip there is a failure. Standard library only.
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


class ScriptTest(unittest.TestCase):
    def test_the_centre_column_is_asked_first_and_the_edges_only_without_it(self):
        code = SCRIPT.read_text(encoding="utf-8")
        body = code[code.index("func _ground_under("):code.index("func _highest_surface(")]
        centre = body.index("_highest_surface(origin.x, origin.y - SINK_WINDOW)")
        edges = body.index("for dx in [-BODY_HALF_WIDTH, BODY_HALF_WIDTH]")
        self.assertLess(centre, body.index("return centre"))
        self.assertLess(body.index("return centre"), edges)
        self.assertIsNone(re.search(r"for dx in \[-BODY_HALF_WIDTH, 0\.0, BODY_HALF_WIDTH\]", code))


class GroundUnderTest(unittest.TestCase):
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

    def test_the_marker_walked_the_whole_level(self):
        self.assertEqual((min(self.ground), max(self.ground)), (102.0, 530.0))

    def test_beside_a_step_the_ground_is_still_the_floor_the_player_stands_on(self):
        # x 428 to 448: the body's right edge is over the step, its centre over the floor.
        # main's harness said 256 here, the step's top.
        self.assertEqual(self.at(102, 448), {320.0, None})
        self.assertEqual(self.at(400, 448), {320.0})
        # And the same on the way out: the left edge is still over the step until x = 532.
        self.assertEqual(self.at(512, 532), {320.0})

    def test_over_the_step_the_ground_is_the_steps_top(self):
        self.assertEqual(self.at(448, 512), {256.0})

    def test_over_a_gap_the_edges_are_asked_and_no_ground_is_no_ground(self):
        # The gap is x 192 to 256. With the centre over it, an edge 20 px to the side still finds
        # the floor until x = 212 and again from x = 236; between them there is nothing under the
        # body at all, and the row has no ground line (a guess is never written).
        self.assertEqual(self.at(192, 212), {320.0})
        self.assertEqual(self.at(212, 236), {None})
        self.assertEqual(self.at(236, 256), {320.0})


if __name__ == "__main__":
    unittest.main()
