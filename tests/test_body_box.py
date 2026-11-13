"""The player's own box in the position log (`body`, the trace contract, November 12, 2026; #259).

The harness logs, each tick, the world box of the player's own collision: how big the engine says
the player is, and where. A visual observer can then be asked about a box that is the game's own
and not a number somebody typed (#330, #327).

Held with the real engine, like tests/test_ground_under.py: the test level's body in several
shapes, and the bundled robot. CI sets EXPECTRAIL_ENGINE_TESTS=required in `capture-smoke`, so a
skip there is a failure. Standard library only.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from harness import run as hr
from tests.test_ground_under import ASIDE, BODY, PROJECT, REPO, SHAPE, both, real_godot, swap


def rows_of(tmp: Path, name: str, scene=None, route: Path | None = None, game: Path | None = None) -> list[dict]:
    """Replay a route and give the trace's rows. `scene` rewrites the test level's main.tscn in a copy."""
    if game is None and route is None:
        game, route = PROJECT / "project", PROJECT / "routes" / "walk.json"
        if scene is not None:
            game = tmp / name / "project"
            shutil.copytree(PROJECT / "project", game)
            text = (game / "main.tscn").read_text(encoding="utf-8")
            changed = scene(text)
            assert changed != text, "the scene was not changed"
            (game / "main.tscn").write_text(changed, encoding="utf-8")
    kwargs = {"game": game} if game is not None else {}
    hr.run(route, tmp / name / "run", godot=real_godot(), capture_frames=False, **kwargs)
    return json.loads((tmp / name / "run" / "trace.json").read_text(encoding="utf-8"))["rows"]


def around_the_origin(rows: list[dict]) -> set:
    """Every row's body box less its player's position: the box as the body carries it."""
    return {tuple(round(b - p, 3) for b, p in zip(r["body"], r["player"] * 2)) for r in rows}


class BodyBoxTest(unittest.TestCase):
    """The test level's player: a shape 24 x 16 on a body moved 2 px a tick from x = 102 at y = 312."""

    @classmethod
    def setUpClass(cls):
        real_godot()
        cls.tmp = Path(tempfile.mkdtemp(prefix="expectrail-body-box-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)

    def test_every_row_has_the_bodys_world_box_and_it_moves_with_the_body(self):
        rows = rows_of(self.tmp, "as-authored")
        self.assertTrue(all("body" in r for r in rows))
        self.assertEqual((rows[0]["player"], rows[0]["body"]), ([102.0, 312.0], [90.0, 304.0, 114.0, 320.0]))
        self.assertEqual((rows[-1]["player"], rows[-1]["body"]), ([530.0, 312.0], [518.0, 304.0, 542.0, 320.0]))
        self.assertEqual(around_the_origin(rows), {(-12.0, -8.0, 12.0, 8.0)})

    def test_a_scaled_body_is_logged_as_big_as_it_stands(self):
        rows = rows_of(self.tmp, "twice", swap(BODY, BODY + "scale = Vector2(2, 2)\n"))
        self.assertEqual(around_the_origin(rows), {(-24.0, -16.0, 24.0, 16.0)})

    def test_a_shape_to_one_side_and_the_same_body_mirrored(self):
        self.assertEqual(around_the_origin(rows_of(self.tmp, "aside", swap(SHAPE, ASIDE))), {(-2.0, -8.0, 22.0, 8.0)})
        mirrored = rows_of(self.tmp, "mirrored", both(swap(SHAPE, ASIDE), swap(BODY, BODY + "scale = Vector2(-1, 1)\n")))
        self.assertEqual(around_the_origin(mirrored), {(-22.0, -8.0, 2.0, 8.0)})

    def test_a_polygon_for_the_collision_is_measured_too(self):
        polygon = ('[node name="CollisionPolygon2D" type="CollisionPolygon2D" parent="Player"]\n'
                   'polygon = PackedVector2Array(-12, -8, 12, -8, 12, 8, -12, 8)\n')
        self.assertEqual(around_the_origin(rows_of(self.tmp, "polygon", swap(SHAPE, polygon))), {(-12.0, -8.0, 12.0, 8.0)})

    def test_a_player_with_no_collision_to_measure_has_no_box_and_none_is_made_up(self):
        rows = rows_of(self.tmp, "disabled", swap(SHAPE, SHAPE + "disabled = true\n"))
        self.assertTrue(rows)
        self.assertFalse(any("body" in r for r in rows))
        self.assertTrue(all("player" in r for r in rows))


class BundledRobotTest(unittest.TestCase):
    """The bundled game on its smoke route: the robot's shape is 42.5 x 54.5, 14 px above its origin."""

    @classmethod
    def setUpClass(cls):
        real_godot()
        cls.tmp = Path(tempfile.mkdtemp(prefix="expectrail-body-robot-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.rows = rows_of(cls.tmp, "smoke", route=REPO / "harness" / "routes" / "smoke.json")

    def test_the_robots_box_is_its_collision_shape_in_every_row(self):
        self.assertEqual(len(self.rows), 240)
        self.assertEqual(around_the_origin(self.rows), {(-21.25, -41.25, 21.25, 13.25)})

    def test_its_bottom_is_the_feet_the_ground_check_has_as_a_constant(self):
        # 13.25 px below the origin is FEET_OFFSET in agents/observations.py, typed in for this robot.
        # The log now says it for any player.
        from agents.observations import FEET_OFFSET
        self.assertEqual({round(r["body"][3] - r["player"][1], 3) for r in self.rows}, {FEET_OFFSET})

    def test_the_log_validates_against_the_trace_contract(self):
        from expectrail.contracts import validate
        trace = json.loads((self.tmp / "smoke" / "run" / "trace.json").read_text(encoding="utf-8"))
        validate(trace, "trace")
        schema = json.loads((REPO / "contracts" / "trace.schema.json").read_text(encoding="utf-8"))
        body = schema["properties"]["rows"]["items"]["properties"]["body"]
        self.assertEqual((body["type"], body["minItems"], body["maxItems"]), ("array", 4, 4))
        example = json.loads((REPO / "contracts" / "examples" / "trace.json").read_text(encoding="utf-8"))
        self.assertEqual(len(example["rows"][0]["body"]), 4)


if __name__ == "__main__":
    unittest.main()
