"""Which surface the harness calls the ground under the player (#348).

The harness asks for the highest solid surface under the player's centre and under its two edges,
because a body rests on the highest point beneath it. Until November 12, 2026 the edges were always
the bundled robot's, 20 px either side. Godot's kinematic character demo has a player 14 px wide:
standing on the floor 20 px from a step it had a column inside the step, the step's top was read as
its ground, and the clean game was rejected (#263). The edges are now the player's own: the two
ends of its collision, measured where the body is in the world.

Two things are held, each with the real engine:
- `tests/projects/stepped-ground`, a level built in code (a floor with its top at y = 320, a gap
  from x = 192 to 256, a 64 px step from x = 448 to 512 with its top at 256) and a body 24 px wide
  moved along it: the ground changes where that body's own edge crosses, not 20 px out. The same
  level again with the body scaled to twice and to half its size, mirrored, with its shape moved
  10 px to one side, and with a polygon for its collision (the merge guard's second review of #349
  found the first version of this measured the shape's own numbers, so a scaled body was wrong).
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
    def test_platforms_exclude_the_player_its_parts_enemies_projectiles_and_rigid_bodies(self):
        code = SCRIPT.read_text(encoding="utf-8")
        body = code[code.index("func _platform_bodies("):code.index("func _platform_shapes(")]
        for needed in ("node is RigidBody2D", "node == _player", "_player.is_ancestor_of(node)",
                       "_is_class(node, _enemy_class)", "_is_class(node, _projectile_class)",
                       "node is StaticBody2D or node is AnimatableBody2D or node is CharacterBody2D"):
            self.assertIn(needed, body)
        shapes = code[code.index("func _platform_shapes("):code.index("static func _highest_in_polygons(")]
        self.assertIn("not shape_node.disabled", shapes)
        self.assertIn("not polygon_node.disabled", shapes)

    def test_the_three_columns_are_asked_and_the_edges_are_the_players_own(self):
        code = SCRIPT.read_text(encoding="utf-8")
        body = code[code.index("func _ground_under("):code.index("func _body_span(")]
        self.assertIn("var span := _body_span(_player)", body)
        self.assertIn("for dx in [span.x, (span.x + span.y) / 2.0, span.y]:", body)
        self.assertNotIn("return centre", body)             # the first attempt: the centre alone when it has a surface
        self.assertNotIn("BODY_HALF_WIDTH", body)            # the constant is the fallback inside _body_span only
        # The bundled robot's shape is 42.5 px wide: its reach is the 20 px it always was.
        inset = float(re.search(r"^const EDGE_INSET := ([\d.]+)$", code, re.M).group(1))
        fallback = float(re.search(r"^const BODY_HALF_WIDTH := ([\d.]+)$", code, re.M).group(1))
        self.assertEqual(42.5 / 2 - inset, fallback)


def ground_by_x(tmp: Path, name: str, scene=None) -> dict:
    """Walk the level and give the logged ground by the player's x. `scene` rewrites main.tscn in a copy."""
    game = PROJECT / "project"
    if scene is not None:
        game = tmp / name / "project"
        shutil.copytree(PROJECT / "project", game)
        text = (game / "main.tscn").read_text(encoding="utf-8")
        changed = scene(text)
        assert changed != text, "the scene was not changed"
        (game / "main.tscn").write_text(changed, encoding="utf-8")
    return {x: g for x, (g, _from) in ground_and_source(tmp, name, game).items()}


def ground_and_source(tmp: Path, name: str, game: Path) -> dict:
    hr.run(PROJECT / "routes" / "walk.json", tmp / name / "run", game=game, godot=real_godot(), capture_frames=False)
    trace = json.loads((tmp / name / "run" / "trace.json").read_text(encoding="utf-8"))
    ground_and_source.header = {k: v for k, v in trace.items() if k != "rows"}
    return {row["player"][0]: (row.get("ground"), row.get("groundFrom")) for row in trace["rows"]}


def swap(old: str, new: str):
    def change(text: str) -> str:
        assert old in text, old
        return text.replace(old, new)
    return change


def both(first, second):
    return lambda text: second(first(text))


BODY = 'position = Vector2(100, 312)\n'
SHAPE = '[node name="CollisionShape2D" type="CollisionShape2D" parent="Player"]\nshape = SubResource("2")\n'
ASIDE = SHAPE.replace("\nshape", "\nposition = Vector2(10, 0)\nshape", 1)     # the shape 10 px right of the origin


class GroundUnderTest(unittest.TestCase):
    """A body 24 px wide: its reach is 12 - 1.25 = 10.75 px either side of its origin."""

    @classmethod
    def setUpClass(cls):
        real_godot()
        cls.tmp = Path(tempfile.mkdtemp(prefix="expectrail-ground-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.ground = ground_by_x(cls.tmp, "as-authored")

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


BRIDGE_SHAPE = '[sub_resource type="RectangleShape2D" id="2"]\nsize = Vector2(24, 16)\n'


def bridge(kind: str, extra: str = "", shape_extra: str = "", y: float = 328):
    """A body 64 by 16 over the gap (x 192 to 256), its top at y = 320, as a platform in a game whose
    platforms are bodies (Godot's kinematic_character demo: CharacterBody2D and StaticBody2D)."""
    def change(text: str) -> str:
        text = text.replace(BRIDGE_SHAPE, BRIDGE_SHAPE + '\n[sub_resource type="RectangleShape2D" id="3"]\nsize = Vector2(64, 16)\n')
        return text + (f'\n[node name="Bridge" type="{kind}" parent="."]\nposition = Vector2(224, {y:g})\n{extra}'
                       f'\n[node name="CollisionShape2D" type="CollisionShape2D" parent="Bridge"]\n'
                       f'shape = SubResource("3")\n{shape_extra}')
    return change


class PlatformBodyTest(unittest.TestCase):
    """Platforms that are bodies are ground (#259, November 13, 2026). Without a body over it the gap
    from x = 204 to 246 has no ground (GroundUnderTest); with one, its top is the ground there."""

    @classmethod
    def setUpClass(cls):
        real_godot()
        cls.tmp = Path(tempfile.mkdtemp(prefix="expectrail-platform-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)

    def walk(self, name: str, scene) -> dict:
        game = self.tmp / name / "project"
        shutil.copytree(PROJECT / "project", game)
        text = (game / "main.tscn").read_text(encoding="utf-8")
        changed = scene(text)
        self.assertNotEqual(changed, text)
        (game / "main.tscn").write_text(changed, encoding="utf-8")
        return ground_and_source(self.tmp, name, game)

    def over_gap(self, ground: dict) -> set:
        return {v for x, v in ground.items() if 204 <= x < 246}

    def test_a_static_body_over_the_gap_is_the_ground_there_and_says_so(self):
        ground = self.walk("static", bridge("StaticBody2D"))
        self.assertEqual(self.over_gap(ground), {(320.0, "body")})
        # Over the floor the tiles are still the ground, and named as tiles.
        self.assertEqual({v for x, v in ground.items() if 102 <= x < 190}, {(320.0, "tile")})
        self.assertEqual(ground_and_source.header["capabilities"]["groundSources"], {"tiles": True, "bodies": 1})

    def test_a_character_body_platform_counts_as_the_demos_platforms_do(self):
        self.assertEqual(self.over_gap(self.walk("character", bridge("CharacterBody2D"))), {(320.0, "body")})

    def test_an_animatable_body_counts(self):
        self.assertEqual(self.over_gap(self.walk("animatable", bridge("AnimatableBody2D"))), {(320.0, "body")})

    def test_a_platform_above_the_players_feet_is_beside_it_not_under_it(self):
        # The body's feet are at y = 320. A platform with its top at 300 is beside the body (or one it
        # is jumping up through), not under it. With the 64 px window tiles have, the first version
        # counted it and rejected the clean kinematic_character demo (outside trial on #388).
        ground = self.walk("beside", bridge("StaticBody2D", y=308))
        self.assertEqual(self.over_gap(ground), {(None, None)})

    def test_a_platform_a_little_below_the_feet_is_under_them(self):
        # Its top at 322: 2 px under the feet, as a body resting on it is.
        self.assertEqual(self.over_gap(self.walk("below", bridge("StaticBody2D", y=330))), {(322.0, "body")})

    def test_a_platform_switched_off_is_not_ground(self):
        # A platform whose collision is disabled (one that crumbles on purpose, or a bug) is not a
        # surface the player should stand on: no ground, so the check needs review, never a reject.
        ground = self.walk("disabled", bridge("StaticBody2D", shape_extra="disabled = true\n"))
        self.assertEqual(self.over_gap(ground), {(None, None)})

    def test_a_rigid_body_and_an_area_are_not_ground(self):
        for kind, extra in (("RigidBody2D", "freeze = true\n"), ("Area2D", "")):
            with self.subTest(kind=kind):
                ground = self.walk(kind.lower(), bridge(kind, extra))
                self.assertEqual(self.over_gap(ground), {(None, None)})
                self.assertEqual(ground_and_source.header["capabilities"]["groundSources"]["bodies"], 0)


class BodyInTheWorldTest(unittest.TestCase):
    """The same level and walk with the body changed in the scene: its ends are measured in the world.

    The step is x 448 to 512 and the gap x 192 to 256; the body is at even x from 102 to 530. A body
    whose ends are `left` and `right` px from its origin (each pulled in by 1.25) has the step as its
    ground from x = 448 - right to 512 - left, and no ground from x = 192 - left to 256 - right.
    """

    @classmethod
    def setUpClass(cls):
        real_godot()
        cls.tmp = Path(tempfile.mkdtemp(prefix="expectrail-body-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)

    def walk(self, name: str, scene) -> dict:
        return ground_by_x(self.tmp, name, scene)

    def at(self, ground: dict, lo: float, hi: float) -> set:
        return {g for x, g in ground.items() if lo <= x < hi}

    def test_a_body_scaled_to_twice_its_size_is_48_px_wide(self):
        # Ends at 24 - 1.25 = 22.75 px. The shape's own numbers say 10.75: the step only from x = 438.
        ground = self.walk("twice", swap(BODY, BODY + "scale = Vector2(2, 2)\n"))
        self.assertEqual(self.at(ground, 236, 426), {320.0})
        self.assertEqual(self.at(ground, 426, 531), {256.0})
        self.assertEqual(self.at(ground, 216, 234), {None})
        self.assertEqual(self.at(ground, 102, 216), {320.0})

    def test_a_body_scaled_to_half_its_size_is_12_px_wide(self):
        # Ends at 6 - 1.25 = 4.75 px. The shape's own numbers put columns 6 px outside this body.
        ground = self.walk("half", swap(BODY, BODY + "scale = Vector2(0.5, 0.5)\n"))
        self.assertEqual(self.at(ground, 252, 444), {320.0})
        self.assertEqual(self.at(ground, 444, 518), {256.0})
        self.assertEqual(self.at(ground, 518, 531), {320.0})
        self.assertEqual(self.at(ground, 198, 252), {None})

    def test_a_scaled_parent_counts(self):
        # The whole scene at 1.5: the tiles are 96 px, the body 36 px wide (ends at 18 - 1.25 = 16.75)
        # and it is moved 3 px a tick from x = 153. The gap is x 288 to 384: no ground from 288 + 16.75
        # to 384 - 16.75. (The shape's own numbers, 10.75: from x = 300 to 372.) The step is 96 px
        # tall here, above the 64 px window, so it is never the ground.
        ground = self.walk("parent", swap('[node name="Main" type="Node2D"]\n',
                                          '[node name="Main" type="Node2D"]\nscale = Vector2(1.5, 1.5)\n'))
        self.assertEqual((min(ground), max(ground)), (153.0, 795.0))
        self.assertEqual(self.at(ground, 153, 306), {480.0})
        self.assertEqual(self.at(ground, 306, 369), {None})
        self.assertEqual(self.at(ground, 369, 796), {480.0})

    def test_a_shape_moved_to_one_side_has_two_different_ends(self):
        # The 24 px shape 10 px right of the origin: the body is x - 2 to x + 22, its ends at -0.75
        # and 20.75 from the origin, and its middle column 10 px right of the origin.
        ground = self.walk("aside", swap(SHAPE, ASIDE))
        self.assertEqual(self.at(ground, 236, 428), {320.0})
        self.assertEqual(self.at(ground, 428, 514), {256.0})        # until its left end, at x - 0.75, leaves 512
        self.assertEqual(self.at(ground, 514, 531), {320.0})
        self.assertEqual(self.at(ground, 194, 236), {None})

    def test_the_same_body_mirrored_has_them_the_other_way_round(self):
        ground = self.walk("mirrored", both(swap(SHAPE, ASIDE), swap(BODY, BODY + "scale = Vector2(-1, 1)\n")))
        # Ends at -20.75 and 0.75: the step from x = 448 - 0.75, until x - 20.75 leaves 512.
        self.assertEqual(self.at(ground, 278, 448), {320.0})
        self.assertEqual(self.at(ground, 448, 531), {256.0})
        self.assertEqual(self.at(ground, 214, 256), {None})

    def test_a_polygon_for_the_collision_is_measured_too(self):
        # No CollisionShape2D: a polygon 24 px wide. Unmeasured, it had the robot's 20 px (the step from 428).
        polygon = ('[node name="CollisionPolygon2D" type="CollisionPolygon2D" parent="Player"]\n'
                   'polygon = PackedVector2Array(-12, -8, 12, -8, 12, 8, -12, 8)\n')
        ground = self.walk("polygon", swap(SHAPE, polygon))
        self.assertEqual(self.at(ground, 246, 438), {320.0})
        self.assertEqual(self.at(ground, 438, 524), {256.0})
        self.assertEqual(self.at(ground, 204, 246), {None})

    def test_with_its_only_shape_disabled_the_robots_20_px_are_used(self):
        ground = self.walk("disabled", swap(SHAPE, SHAPE + "disabled = true\n"))
        self.assertEqual(self.at(ground, 428, 531), {256.0})
        self.assertEqual(self.at(ground, 236, 428), {320.0})


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
