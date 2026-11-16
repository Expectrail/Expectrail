"""Generic screen geometry tests, independent of particular defects and image packages."""
import copy
import unittest

from tools.playtester.offscreen import findings, outside, viewport_size
from tools.playtester.producer import OFFSCREEN, reports


def row(body=None, view=None):
    return {"player": [105, 25], "playerVisible": True,
            "body": body if body is not None else [101, 20, 111, 30],
            "view": view if view is not None else [1, 0, 0, 1, 0, 0]}


def trace(rows, rate=2):
    return {"rows": [dict(r, tick=i) for i, r in enumerate(rows)], "physicsTicksPerSecond": rate}


class OffscreenTest(unittest.TestCase):
    def test_whole_body_must_leave_the_view_not_just_the_origin(self):
        self.assertTrue(outside(row(), (100, 80)))
        self.assertFalse(outside(row([90, 20, 101, 30]), (100, 80)))
        for body in ([-10, 0, 0, 10], [100, 0, 110, 10], [0, -10, 10, 0], [0, 80, 10, 90]):
            self.assertFalse(outside(row(body), (100, 80)))
        for body in ([-11, 0, -1, 10], [101, 0, 111, 10], [0, -11, 10, -1], [0, 81, 10, 91]):
            self.assertTrue(outside(row(body), (100, 80)))

    def test_uses_full_affine_transform_including_mirrors_and_rotation(self):
        self.assertTrue(outside(row([10, 20, 20, 30], [2, 0, 0, 2, 100, 0]), (100, 80)))
        self.assertFalse(outside(row([10, 20, 20, 30], [-1, 0, 0, 1, 50, 0]), (100, 80)))
        self.assertTrue(outside(row([0, 10, 5, 15], [0, 1, -1, 0, 0, 0]), (100, 80)))

    def test_requires_one_full_physics_second_and_anchors_previous_tick(self):
        recorded = trace([row([0, 0, 10, 10]), row(), row()])
        self.assertEqual(findings(trace(recorded["rows"][:2]), (100, 80)), [])
        found = findings(recorded, (100, 80))[0]
        self.assertEqual(found["bug"], OFFSCREEN)
        self.assertEqual(found["fault"], {"preFaultTick": 1, "faultTick": 2,
            "anchor": {"object": "Player", "x": 105, "y": 25, "tolerancePx": 2}})

    def test_visible_sample_or_missing_evidence_breaks_the_window(self):
        for key in ("player", "body", "view", "playerVisible"):
            absent = row()
            absent.pop(key)
            self.assertEqual(findings(trace([row(), absent, row()]), (100, 80)), [])
        self.assertEqual(findings(trace([row(), row([0, 0, 10, 10]), row()]), (100, 80)), [])
        hidden = row()
        hidden["playerVisible"] = False
        self.assertIsNone(outside(hidden, (100, 80)))

    def test_invalid_or_degenerate_geometry_is_unknown(self):
        for bad in (row([11, 20, 10, 30]), row(view=[0, 0, 0, 0, 0, 0]),
                    row(view=[1, 0, 0, 1, float("nan"), 0]), row(body=[True, 0, 2, 3])):
            self.assertIsNone(outside(bad, (100, 80)))
        for dims in ((0, 1), (1, -2), (True, 80), (float("inf"), 1), (1,)):
            with self.assertRaises(ValueError):
                viewport_size(dims)
        for rate in (None, 0, True):
            with self.assertRaises(ValueError):
                findings(trace([row()], rate), (100, 80))

    def test_policy_is_opt_in_deterministic_and_keeps_exact_report_shape(self):
        recorded = trace([row(), row(), row()])
        route = {"format": "expectrail.route/v0", "name": "screen", "ticks": 3, "events": []}
        self.assertEqual(reports(route, recorded, "a"*40), [])
        new = reports(route, recorded, "a"*40, viewport=(100, 80))
        self.assertEqual(new, reports(route, copy.deepcopy(recorded), "a"*40, viewport=(100, 80)))
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["producer"], {"name": "Expectrail", "version": "1.1.0"})
        self.assertEqual(set(new[0]), {"format", "id", "producer", "target", "route", "bug", "fault"})

    def test_original_observations_are_retained_in_the_combined_policy(self):
        recorded = trace([dict(row(), player=[i, 25], facing=(-1)**i) for i in range(20)], rate=120)
        route = {"events": []}
        original = reports(route, recorded, "a"*40)
        improved = reports(route, recorded, "a"*40, viewport=(100, 80))
        self.assertTrue(original)
        self.assertEqual([(r["bug"], r["fault"]) for r in original],
                         [(r["bug"], r["fault"]) for r in improved])
        self.assertEqual(original[0]["producer"]["version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
