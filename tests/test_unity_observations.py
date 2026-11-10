"""agents.unity_observations: the Unity trace as engine observations, judged by the unchanged evaluator."""
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from agents import unity_observations as uo
from expectrail.evaluator import evaluate

# view: 0.5 frame px per world px, origin at (100, 500). The ground at world y 400 is frame y 700.
VIEW = [0.5, 0.0, 0.0, 0.5, 100.0, 500.0]


def _row(t: int, bottom: float = 700.0, visible: bool = True, ground: float | None = 400.0, coins=1, on_floor=True):
    objects = [{"id": "Player", "role": "player", "box": [300.0, bottom - 80.0, 340.0, bottom],
                "active": True, "visible": visible}]
    objects += [{"id": f"Coins/Coin{k}", "role": "coin", "box": [500.0 + 40 * k, 600.0, 520.0 + 40 * k, 620.0],
                 "active": True, "visible": True} for k in range(coins)]
    row = {"tick": t, "frame": t, "player": [400.0, 400.0], "onFloor": on_floor, "view": VIEW, "objects": objects}
    if ground is not None:
        row["ground"] = ground
    return row


def _trace(rows):
    return {"format": "expectrail.trace/v0", "ticks": len(rows), "rows": rows}


def _spec(kind: str, obj: str, **extra):
    spec = {"format": "expectrail.test-spec/v0", "id": f"t-{kind}", "instruction": "x",
            "objects": {obj: {"prompt": obj}}, "assertion": {"type": kind, "object": obj},
            "window": {"fromFrame": 0}}
    if kind == "never-crosses":
        spec["objects"]["ground"] = {"prompt": "ground"}
        spec["assertion"]["boundary"] = {"relativeTo": "ground", "edge": "top", "side": "above",
                                         "tolerancePx": extra.get("tol", 5)}
    return spec


GROUND_SPEC = _spec("never-crosses", "player")
VISIBLE_SPEC = _spec("visible", "player")
COINS_SPEC = _spec("visible", "coin")


class UnityObservations(unittest.TestCase):
    def test_a_standing_player_passes_the_ground_and_visible_specs(self):
        trace = _trace([_row(t) for t in range(5)])
        self.assertEqual(evaluate(GROUND_SPEC, uo.observations(trace, GROUND_SPEC))["result"], "pass")
        self.assertEqual(evaluate(VISIBLE_SPEC, uo.observations(trace, VISIBLE_SPEC))["result"], "pass")
        self.assertEqual(evaluate(COINS_SPEC, uo.observations(trace, COINS_SPEC))["result"], "pass")

    def test_the_ground_line_uses_the_camera_of_the_frame(self):
        rows = [_row(0), _row(1)]
        rows[1]["view"] = [0.5, 0.0, 0.0, 0.5, 100.0, 510.0]  # row 1 holds frame 0's camera
        self.assertEqual(uo.ground_line(rows, 0), 710.0)
        self.assertEqual(uo.ground_line(rows, 1), 710.0)  # the last row keeps its own

    def test_a_sunk_player_fails_and_names_the_first_frame(self):
        trace = _trace([_row(0), _row(1), _row(2, bottom=730.0), _row(3, bottom=760.0)])
        verdict = evaluate(GROUND_SPEC, uo.observations(trace, GROUND_SPEC))
        self.assertEqual((verdict["result"], verdict["firstFrame"]), ("fail", 2))

    def test_an_invisible_player_fails_visible_and_is_needs_review_on_the_ground(self):
        trace = _trace([_row(0), _row(1, visible=False), _row(2)])
        self.assertEqual(evaluate(VISIBLE_SPEC, uo.observations(trace, VISIBLE_SPEC))["result"], "fail")
        self.assertEqual(evaluate(GROUND_SPEC, uo.observations(trace, GROUND_SPEC))["result"], "needs-review")

    def test_no_ground_line_is_needs_review_never_a_pass(self):
        trace = _trace([_row(0), _row(1, ground=None)])
        self.assertEqual(evaluate(GROUND_SPEC, uo.observations(trace, GROUND_SPEC))["result"], "needs-review")

    def test_an_object_outside_the_frame_is_absent(self):
        row = _row(0)
        row["objects"][0]["box"] = [1700.0, 100.0, 1740.0, 180.0]
        self.assertEqual(uo.role_boxes(row, "player"), [])

    def test_a_name_the_trace_does_not_have_is_refused(self):
        with self.assertRaises(ValueError):
            uo.observations(_trace([_row(0)]), _spec("visible", "robot"))

    def test_the_sam_filter_keeps_only_boxes_on_the_engine_box(self):
        trace = _trace([_row(0, coins=2)])
        keep = uo.agreeing(trace, ["coin", "player"])
        on = {"box": [501.0, 601.0, 521.0, 621.0], "score": 0.9}
        off = {"box": [900.0, 100.0, 920.0, 120.0], "score": 0.9}
        player = {"box": [300.0, 620.0, 340.0, 700.0], "score": 0.8}
        kept = keep({0: {"coin": [on, off], "player": [player]}, 5: {"coin": [on]}})
        self.assertEqual(kept[0]["coin"], [on])
        self.assertEqual(kept[0]["player"], [player])
        self.assertEqual(kept[5]["coin"], [])  # a frame with no row keeps nothing
        self.assertEqual(uo.engine_objects(trace, ["ground"])[0]["ground"][0]["box"][1], 700.0)

    def test_calibrate_measures_the_box_against_the_ground(self):
        rows = [_row(0), _row(1, bottom=702.0), _row(2, bottom=650.0, on_floor=False, coins=0)]
        c = uo.calibrate(_trace(rows))
        self.assertEqual(c["playerVisible"], 3)
        self.assertEqual(c["onFloorBottomMinusGround"], {"n": 2, "min": 0.0, "median": 1.0, "max": 2.0})
        self.assertEqual(c["airborneBottomMinusGround"]["min"], -50.0)
        self.assertEqual(c["onFloorOffGround"]["rows"], 0)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            path.write_text(json.dumps(_trace(rows)))
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(uo.main(["calibrate", str(path)]), 0)
            self.assertIn("on the floor 0.0/1.0/2.0 (n 2)", out.getvalue())


    def test_calibrate_counts_floor_rows_standing_off_the_ground_tilemap(self):
        rows = [_row(0), _row(1, bottom=600.0), _row(2, bottom=600.0), _row(3), _row(4, bottom=500.0)]
        c = uo.calibrate(_trace(rows))
        self.assertEqual(c["onFloorOffGround"]["rows"], 3)
        self.assertEqual(c["onFloorOffGround"]["spans"], [[1, 2], [4, 4]])
        self.assertEqual(c["onFloorOffGround"]["onGround"]["max"], 0.0)
        self.assertIn("on 3 rows (ticks 1-2, 4)", uo.calibration_line(c))
        self.assertEqual(c["coinsVisiblePerFrame"]["max"], 1.0)


if __name__ == "__main__":
    unittest.main()


# Level surfaces as the Unity harness records them: closed paths in world px, y down.
FLOOR = [[0.0, 700.0], [2000.0, 700.0], [2000.0, 900.0], [0.0, 900.0]]
# One composite path: a ceiling slab (y 300 to 350) joined by a wall at x 0 to 50 to the floor (700 to 900).
C_SHAPE = [[0.0, 300.0], [2000.0, 300.0], [2000.0, 350.0], [50.0, 350.0], [50.0, 700.0],
           [2000.0, 700.0], [2000.0, 900.0], [0.0, 900.0]]


class UnityReferenceGround(unittest.TestCase):
    def test_the_first_surface_below_the_window_is_the_ground(self):
        # Origin at y 572: the search starts at 508 and meets the floor's top at 700.
        self.assertEqual(uo.reference_ground([FLOOR], 400.0, 572.0), 700.0)

    def test_an_overhang_in_the_same_path_does_not_hide_the_floor(self):
        self.assertEqual(uo.reference_ground([C_SHAPE], 400.0, 572.0), 700.0)
        # The Godot search takes the path's top edge (the ceiling, 300), finds it above its window and
        # drops the whole path: why it missed the Unity ground on 141 of 200 rows in run 8.
        from agents.observations import surface_under
        self.assertIsNone(surface_under([C_SHAPE], 400.0, 572.0))

    def test_a_buried_body_gets_the_top_of_the_solid_it_is_in(self):
        # Origin at 800: the search starts at 736, inside the floor; the ground is its top, 700.
        self.assertEqual(uo.reference_ground([FLOOR], 400.0, 800.0), 700.0)

    def test_a_floor_beyond_the_search_depth_is_no_ground(self):
        config = {"window": 64.0, "half": 20.0, "depth": 100.0}
        self.assertIsNone(uo.reference_ground([FLOOR], 400.0, 300.0, config))
        self.assertEqual(uo.reference_ground([FLOOR], 400.0, 300.0), 700.0)  # 16 cells reach it

    def test_the_highest_of_the_three_columns_wins(self):
        ledge = [[410.0, 650.0], [600.0, 650.0], [600.0, 700.0], [410.0, 700.0]]
        # The right column (x 420) is over the ledge at 650; the others over the floor at 700.
        self.assertEqual(uo.reference_ground([FLOOR, ledge], 400.0, 572.0), 650.0)
        self.assertEqual(uo.reference_ground([FLOOR, ledge], 300.0, 572.0), 700.0)

    def test_a_candidate_that_moved_its_ground_is_judged_on_the_clean_level(self):
        # The player's box bottom is at frame y 730. The candidate's level put the ground lower, at world
        # y 460 (frame y 730 with VIEW), so on its own ground the player looks like it stands: pass.
        rows = [_row(t, bottom=730.0) for t in range(3)]
        for r in rows:
            r["player"], r["ground"] = [400.0, 572.0], 460.0
        trace = _trace(rows)
        self.assertEqual(evaluate(GROUND_SPEC, uo.observations(trace, GROUND_SPEC))["result"], "pass")
        # The clean level's floor is at world y 400 (frame y 700): on it the player is 30 px sunk.
        clean = [[0.0, 400.0], [2000.0, 400.0], [2000.0, 900.0], [0.0, 900.0]]
        judged = uo.with_reference_ground(trace, [clean])
        self.assertEqual((judged["groundReference"], judged["rows"][0]["ground"]), ("clean level", 400.0))
        self.assertEqual(evaluate(GROUND_SPEC, uo.observations(judged, GROUND_SPEC))["result"], "fail")

    def test_reference_agreement_on_a_consistent_trace(self):
        rows = [{"tick": t, "frame": t, "player": [400.0, 572.0], "ground": 700.0} for t in range(4)]
        rows.append({"tick": 4, "frame": 4, "player": [400.0, 572.0], "ground": 703.0})
        a = uo.reference_agreement({"levelSurfaces": [FLOOR], "rows": rows})
        self.assertEqual((a["both"], a["within1px"], a["largestGap"]), (5, 4, 3.0))

    def test_the_config_comes_from_the_harness_map(self):
        from harness.run import REPO
        c = uo.load_ground_config(REPO / "harness" / "unity" / "maps" / "unity-platformer.json")
        self.assertEqual(c, {"window": 64.0, "half": 20.0, "depth": 16 * 128.0})
