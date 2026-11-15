"""Enemies' and bullets' own boxes in the position log (`enemyBoxes`, `projectileBoxes`; #286).

A pixel check that can name the bullet or an enemy needs to know where each is drawn, as the player's
`body` box says for the player. The harness now logs, every tick, the world box of each tracked
enemy's and projectile's own collision, matched to its position by id, and says so in the header
(`capabilities.objectBoxes`). agents/sam_anchor.py ``object_boxes`` turns them into boxes in a frame.

The engine half (BundledGameTest) runs the bundled game on harness/routes/combat.json, like
tests/test_body_box.py. The suite's job has no engine, so it skips there; `capture-smoke` runs
BundledGameTest with EXPECTRAIL_ENGINE_TESTS=required, so a missing engine there is a failure.
"""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agents.sam_anchor import DEFAULT_PAD, OBJECT_BOXES, anchors, object_boxes
from tests.geometry_fixture import replay_trace
from tests.test_ground_under import REPO, real_godot


class BundledGameTest(unittest.TestCase):
    """The bundled game on the combat route: three enemies from the start, and bullets fired."""

    @classmethod
    def setUpClass(cls):
        godot = real_godot()
        cls.tmp = Path(tempfile.mkdtemp(prefix="expectrail-object-boxes-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.trace = replay_trace(REPO / "game" / "platformer", REPO / "harness" / "routes" / "combat.json",
                                 cls.tmp / "run", godot)
        cls.rows = cls.trace["rows"]

    def test_the_header_says_the_rows_carry_object_boxes(self):
        self.assertIs(self.trace["capabilities"]["objectBoxes"], True)
        self.assertTrue(all("enemyBoxes" in r and "projectileBoxes" in r for r in self.rows))

    def test_every_listed_enemy_and_bullet_has_a_box_with_its_own_id(self):
        for row in self.rows:
            self.assertEqual([e[0] for e in row["enemies"]], [b[0] for b in row["enemyBoxes"]])
            self.assertEqual([p[0] for p in row["projectiles"]], [b[0] for b in row["projectileBoxes"]])
        self.assertTrue(any(r["projectileBoxes"] for r in self.rows), "the route fires no bullet")

    def test_each_box_is_the_collision_shape_around_its_position(self):
        # The bundled bullet's shape is a circle of radius 8; the enemy's measures 50 x 36, 18 px above
        # and below its origin. Measured on the curve, so a size may be a hundredth short.
        for row in self.rows:
            for kind, positions, boxes, size in (("enemy", row["enemies"], row["enemyBoxes"], (50.0, 36.0)),
                                                 ("bullet", row["projectiles"], row["projectileBoxes"], (16.0, 16.0))):
                at = {p[0]: p[1:] for p in positions}
                for ident, left, top, right, bottom in boxes:
                    with self.subTest(kind=kind, tick=row["tick"], id=ident):
                        self.assertAlmostEqual(right - left, size[0], delta=0.03)
                        self.assertAlmostEqual(bottom - top, size[1], delta=0.03)
                        x, y = at[ident]
                        self.assertAlmostEqual((left + right) / 2, x, delta=0.03)
                        self.assertAlmostEqual((top + bottom) / 2, y, delta=0.03)

    def test_the_reader_places_a_bullet_where_the_camera_draws_it(self):
        # At 120 ticks a second and 60 frames, frame n shows tick 2n + 1 (agents/observations.py, _frame_tick).
        tick = next(r["tick"] for r in self.rows if r["projectileBoxes"] and r["tick"] % 2 == 1)
        frame = (tick - 1) // 2
        got = object_boxes(self.trace, (1152, 648), [frame], "bullet")[frame]
        self.assertNotIn("why", got)
        self.assertEqual(len(got["boxes"]) + got["outside"], len(self.rows[tick]["projectileBoxes"]))
        self.assertTrue(got["boxes"], "the first bullet is fired on screen")
        self.assertEqual({b["id"] for b in got["boxes"]}, {p[0] for p in self.rows[tick]["projectiles"]})


class ContractTest(unittest.TestCase):
    """The trace contract's new fields: no engine needed."""

    def setUp(self):
        self.schema = json.loads((REPO / "contracts" / "trace.schema.json").read_text(encoding="utf-8"))
        self.example = json.loads((REPO / "contracts" / "examples" / "trace-godot.json").read_text(encoding="utf-8"))

    def test_the_schema_has_the_fields_and_the_godot_example_carries_them(self):
        rows = self.schema["properties"]["rows"]["items"]["properties"]
        self.assertEqual(rows["enemyBoxes"]["items"], {"$ref": "#/$defs/trackedBox"})
        self.assertEqual(rows["projectileBoxes"]["items"], {"$ref": "#/$defs/trackedBox"})
        self.assertEqual(self.schema["properties"]["capabilities"]["properties"]["objectBoxes"]["type"], "boolean")
        self.assertIs(self.example["capabilities"]["objectBoxes"], True)
        self.assertTrue(any(r["projectileBoxes"] for r in self.example["rows"]))
        for row in self.example["rows"]:
            self.assertEqual([e[0] for e in row["enemies"]], [b[0] for b in row["enemyBoxes"]])
            self.assertEqual([p[0] for p in row["projectiles"]], [b[0] for b in row["projectileBoxes"]])

    def test_both_examples_validate_and_a_malformed_box_is_refused(self):
        # No skip: the suite's job installs jsonschema (requirements-dev.txt), so a missing package fails
        # here. The engine job runs only BundledGameTest, which needs no jsonschema.
        import jsonschema  # noqa: F401
        from expectrail.contracts import validate
        validate(self.example, "trace")
        validate(json.loads((REPO / "contracts" / "examples" / "trace.json").read_text(encoding="utf-8")), "trace")
        for name, change in {
            "four numbers, no id": lambda r: r.__setitem__("projectileBoxes", [[1.0, 2.0, 3.0, 4.0]]),
            "an id that is not a whole number": lambda r: r.__setitem__("enemyBoxes", [[0.5, 1.0, 2.0, 3.0, 4.0]]),
            "six items": lambda r: r.__setitem__("enemyBoxes", [[0, 1.0, 2.0, 3.0, 4.0, 5.0]]),
        }.items():
            with self.subTest(name):
                bad = copy.deepcopy(self.example)
                change(bad["rows"][0])
                with self.assertRaises(Exception):
                    validate(bad, "trace")


def trace(rows, boxes=True, ticks_per_second=120):
    return {"physicsTicksPerSecond": ticks_per_second, "rows": rows,
            "capabilities": {"objectBoxes": True} if boxes else {}}


def row(tick, view=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0), bullets=(), enemies=()):
    out = {"tick": tick, "player": [20.0, 20.0], "body": [16.0, 16.0, 24.0, 24.0], "enemyBoxes": list(enemies),
           "projectileBoxes": list(bullets)}
    if view is not None:
        out["view"] = list(view)
    return out


class ReaderTest(unittest.TestCase):
    """agents/sam_anchor.py ``object_boxes``: from logged world boxes to boxes in a frame."""

    SIZE = (100, 80)

    def test_a_box_is_widened_by_the_pad_and_placed_as_the_players_is(self):
        # Frame 0 shows tick 1. A bullet logged at [40, 30, 48, 38] with the identity camera is
        # [36, 26, 52, 42] once widened by 4 game pixels; the player's body box is placed the same way.
        rows = [row(0), row(1, bullets=[[7, 40.0, 30.0, 48.0, 38.0]]), row(2)]
        got = object_boxes(trace(rows), self.SIZE, [0], "bullet")
        self.assertEqual(got, {0: {"boxes": [{"id": 7, "world": [40.0, 30.0, 48.0, 38.0],
                                              "promptBox": [36, 26, 52, 42]}], "outside": 0}})
        player = anchors(trace(rows), self.SIZE, [0], box="body", pad=DEFAULT_PAD)[0]["promptBox"]
        self.assertEqual(player, [12, 12, 28, 28])

    def test_the_camera_scales_and_moves_the_box(self):
        # The frame showing tick 1 is drawn with the camera logged on tick 2: twice the size, 10 px left.
        rows = [row(0), row(1, enemies=[[3, 10.0, 10.0, 20.0, 20.0]]), row(2, view=(2.0, 0.0, 0.0, 2.0, -10.0, 0.0))]
        got = object_boxes(trace(rows), self.SIZE, [0], "enemy", pad=0)[0]
        self.assertEqual(got["boxes"][0]["promptBox"], [10, 20, 30, 40])

    def test_a_box_wholly_outside_the_picture_is_counted_not_listed_and_one_half_in_is_cut(self):
        rows = [row(0), row(1, bullets=[[1, 200.0, 10.0, 208.0, 18.0], [2, 96.0, 10.0, 104.0, 18.0]]), row(2)]
        got = object_boxes(trace(rows), self.SIZE, [0], "bullet")[0]
        self.assertEqual(got["outside"], 1)
        self.assertEqual([(b["id"], b["promptBox"]) for b in got["boxes"]], [(2, [92, 6, 100, 22])])

    def test_none_on_screen_is_an_answer_and_not_a_gap(self):
        got = object_boxes(trace([row(0), row(1), row(2)]), self.SIZE, [0], "enemy")
        self.assertEqual(got, {0: {"boxes": [], "outside": 0}})

    def test_a_trace_that_does_not_log_boxes_is_never_guessed_from_positions(self):
        rows = [dict(row(t), enemies=[[0, 50.0, 40.0]]) for t in range(3)]
        for r in rows:
            r.pop("enemyBoxes")
            r.pop("projectileBoxes")
        got = object_boxes(trace(rows, boxes=False), self.SIZE, [0], "enemy")[0]
        self.assertIn("no objectBoxes in its header", got["why"])
        # A header that says it logs them, and a row without the field, is a gap for that frame.
        got = object_boxes(trace(rows), self.SIZE, [0], "enemy")[0]
        self.assertIn("no enemyBoxes on this tick", got["why"])

    def test_a_frame_past_the_log_or_without_a_camera_is_a_gap(self):
        got = object_boxes(trace([row(0), row(1)]), self.SIZE, [5], "bullet")
        self.assertIn("ends before this frame", got[5]["why"])
        got = object_boxes(trace([row(0, view=None), row(1, view=None), row(2, view=None)]), self.SIZE, [0], "bullet")
        self.assertIn("no camera", got[0]["why"])

    def test_only_a_role_the_engine_logs_a_box_for_can_be_asked_about(self):
        self.assertEqual(OBJECT_BOXES, {"enemy": "enemyBoxes", "bullet": "projectileBoxes"})
        with self.assertRaisesRegex(ValueError, "logs no box for 'coin'"):
            object_boxes(trace([row(0)]), self.SIZE, [0], "coin")


if __name__ == "__main__":
    unittest.main()
