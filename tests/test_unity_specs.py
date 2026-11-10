"""The Unity specs in specs/unity/: valid, lint-clean, observable on a Unity trace, and kept from the Godot game."""
import glob
import json
import unittest
from pathlib import Path

from agents import unity_observations as uo
from expectrail.contracts import validate
from expectrail.evaluator import evaluate
from expectrail.spec_writer import lint
from harness.run import REPO

UNITY = sorted((REPO / "specs" / "unity").glob("*.json"))


def _trace(gaps):
    """A clean-looking trace: the box bottom ``gap`` px below the ground line (negative is above)."""
    view = [0.5, 0.0, 0.0, 0.5, 100.0, 500.0]  # ground world y 400 -> frame y 700
    rows = []
    for t, gap in enumerate(gaps):
        rows.append({"tick": t, "frame": t, "player": [400.0, 400.0], "onFloor": True, "ground": 400.0, "view": view,
                     "objects": [{"id": "Player", "role": "player", "box": [300.0, 560.0 + gap, 340.0, 700.0 + gap],
                                  "active": True, "visible": True},
                                 {"id": "Coins/GoldCoin", "role": "coin", "box": [500.0, 600.0, 590.0, 690.0],
                                  "active": True, "visible": True}]})
    return {"format": "expectrail.trace/v0", "ticks": len(rows), "rows": rows}


class UnitySpecs(unittest.TestCase):
    def test_the_three_drafts_are_there_valid_and_lint_clean(self):
        self.assertEqual([p.stem for p in UNITY],
                         ["unity-coins-visible", "unity-player-always-visible", "unity-player-stays-above-ground"])
        for path in UNITY:
            with self.subTest(spec=path.name):
                doc = json.loads(path.read_text(encoding="utf-8"))
                validate(doc, "test-spec")
                self.assertEqual(doc["id"], path.stem)
                # A draft carries no approval; lint says so once a person has approved it.
                self.assertEqual([p for p in lint(doc) if "approval" not in p], [])
                self.assertEqual(doc["window"], {"fromFrame": 0, "toFrame": 199})

    def test_every_object_they_name_is_one_the_unity_trace_has(self):
        for path in UNITY:
            doc = json.loads(path.read_text(encoding="utf-8"))
            uo.observations(_trace([-1.0]), doc)  # raises on a name the trace does not have

    def test_the_godot_loaders_do_not_read_them(self):
        godot = {Path(p).name for p in glob.glob(str(REPO / "specs" / "*.json"))}
        self.assertFalse(any(p.name in godot for p in UNITY))

    def test_the_ground_tolerance_passes_the_clean_range_and_fails_a_sink_past_it(self):
        spec = json.loads((REPO / "specs" / "unity" / "unity-player-stays-above-ground.json").read_text())
        self.assertEqual(spec["assertion"]["boundary"]["tolerancePx"], 4)
        # docs/unity.md: on the floor the clean bottom sits 0.98 to 1.25 px above the line.
        clean = _trace([-1.25, -1.13, -0.98] * 10)
        self.assertEqual(evaluate(spec, uo.observations(clean, spec))["result"], "pass")
        sunk = _trace([-1.0] * 10 + [4.5] * 3)
        verdict = evaluate(spec, uo.observations(sunk, spec))
        self.assertEqual((verdict["result"], verdict["firstFrame"]), ("fail", 10))


if __name__ == "__main__":
    unittest.main()
