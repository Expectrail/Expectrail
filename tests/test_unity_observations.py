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
        self.assertEqual(c["coinsVisiblePerFrame"]["max"], 1.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            path.write_text(json.dumps(_trace(rows)))
            out = StringIO()
            with redirect_stdout(out):
                self.assertEqual(uo.main(["calibrate", str(path)]), 0)
            self.assertIn("on the floor 0.0/1.0/2.0 (n 2)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
