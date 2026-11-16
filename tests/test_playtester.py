"""Engine-independent tests for the bounded producer and the engine-only experiment."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from expectrail.route import RouteError, read_trace
from tools.playtester.bench import filter_result, replay_result
from tools.playtester.producer import FALL, FACING, STUCK, anomalies, make_route, play, reports

COMMIT = "a" * 40


def trace(rows):
    return {"format": "expectrail.trace/v0", "ticks": len(rows),
            "physicsTicksPerSecond": 120, "rows": [dict(tick=i, **r) for i, r in enumerate(rows)]}


class PlaytesterTest(unittest.TestCase):
    def test_seed_and_map_order_reproduce_route_and_only_map_actions_are_used(self):
        actions = ["move_right", "move_left", "jump", "shoot", "toggle_pause", "jump_p2"]
        route = make_route(actions, 123)
        self.assertEqual(route, make_route(list(reversed(actions)), 123))
        self.assertNotEqual(route, make_route(actions, 124))
        self.assertTrue({e["action"] for e in route["events"]} <= set(actions[:4]))
        held = set()
        for event in route["events"]:
            self.assertTrue(0 <= event["tick"] < route["ticks"])
            if event["pressed"]:
                self.assertNotIn(event["action"], held)
                held.add(event["action"])
            else:
                self.assertIn(event["action"], held)
                held.remove(event["action"])
        self.assertFalse(held)

    def test_route_bounds_and_missing_movement(self):
        for ticks in (1, 1800):
            self.assertEqual(make_route(["ui_left"], 0, ticks)["ticks"], ticks)
        for ticks in (0, 1801, True):
            with self.assertRaises(ValueError):
                make_route(["ui_left"], 0, ticks)
        for seed in (-1, 2**32, True):
            with self.assertRaises(ValueError):
                make_route(["ui_left"], seed)
        with self.assertRaises(ValueError):
            make_route(["pause"], 0)

    def test_report_shape_anchor_and_deterministic_id(self):
        route = make_route(["move_right"], 42, 10)
        recorded = trace([{"player": [10, 10]}, {"player": [11, 165]}])
        recorded["levelSurfaces"] = [[[0, 100], [20, 100]]]
        document = reports(route, recorded, COMMIT)[0]
        self.assertEqual(document, reports(route, copy.deepcopy(recorded), COMMIT)[0])
        self.assertEqual(set(document), {"format", "id", "producer", "target", "route", "bug", "fault"})
        self.assertEqual(document["format"], "expectrail.playtest-report/v1")
        self.assertRegex(document["id"], r"^[a-z0-9][a-z0-9-]{3,63}$")
        self.assertEqual(document["bug"], FALL)
        self.assertEqual(document["fault"], {"preFaultTick": 0, "faultTick": 1,
            "anchor": {"object": "Player", "x": 10, "y": 10, "tolerancePx": 2}})
        self.assertNotEqual(document["id"], reports(route, recorded, "b" * 40)[0]["id"])
        with self.assertRaises(ValueError):
            reports(route, recorded, "main")

    def test_below_level_requires_geometry_and_strict_threshold(self):
        route = make_route(["move_right"], 0, 3)
        recorded = trace([{"player": [0, y]} for y in (100, 164, 165)])
        self.assertEqual(anomalies(route, recorded), [])
        recorded["levelSurfaces"] = [[[0, 100]]]
        self.assertEqual(anomalies(route, recorded)[0]["fault"]["faultTick"], 2)

    def test_stopped_requires_full_continuous_hold_and_complete_positions(self):
        route = {"events": [{"tick": 0, "action": "move_right", "pressed": True}]}
        recorded = trace([{"player": [0, 0]} for _ in range(121)])
        findings = anomalies(route, recorded)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["bug"], STUCK)
        self.assertEqual(findings[0]["fault"]["faultTick"], 119)
        recorded["rows"][60].pop("player")
        self.assertEqual(anomalies(route, recorded), [])
        self.assertEqual(anomalies({"events": []}, trace([{"player": [0, 0]}] * 240)), [])

    def test_stopped_window_resets_on_direction_change(self):
        route = {"events": [{"tick": 0, "action": "move_right", "pressed": True},
                            {"tick": 90, "action": "move_right", "pressed": False},
                            {"tick": 90, "action": "move_left", "pressed": True}]}
        self.assertEqual(anomalies(route, trace([{"player": [0, 0]}] * 180)), [])

    def test_facing_alternation_requires_sustained_motion(self):
        route = {"events": []}
        recorded = trace([{"player": [i, 0], "facing": (-1)**i} for i in range(20)])
        finding = anomalies(route, recorded)[0]
        self.assertEqual(finding["bug"], FACING)
        self.assertEqual(finding["fault"]["faultTick"], 9)
        for row in recorded["rows"]:
            row["player"][0] = 0
        self.assertEqual(anomalies(route, recorded), [])

    def test_clean_motion_and_missing_fields_are_not_fabricated(self):
        route = {"events": []}
        recorded = trace([{"player": [i, 0], "facing": 1} for i in range(200)])
        self.assertEqual(anomalies(route, recorded), [])
        self.assertEqual(anomalies(route, trace([{} for _ in range(200)])), [])

    def test_filter_measures_wrong_anchor_even_when_symptom_reproduces(self):
        route = {"format": "expectrail.route/v0", "name": "test", "ticks": 2, "events": []}
        recorded = trace([{"player": [0, 0]}, {"player": [0, 200]}])
        recorded["levelSurfaces"] = [[[0, 100]]]
        report = reports(route, recorded, COMMIT)[0]
        result = replay_result(report, recorded)
        self.assertEqual(result, {"anchorReached": True, "anomalyReproduced": True})
        self.assertEqual(filter_result([result] * 3), "reproduced")
        report["fault"]["anchor"]["x"] = 10000
        result = replay_result(report, recorded)
        self.assertEqual(result, {"anchorReached": False, "anomalyReproduced": True})
        self.assertEqual(filter_result([result] * 3), "anchor-desync")

    def test_filter_requires_three_reproductions_and_anchor_tolerance_is_inclusive(self):
        route = {"events": []}
        recorded = trace([{"player": [0, 0]}, {"player": [0, 200]}])
        recorded["levelSurfaces"] = [[[0, 100]]]
        report = reports(route, recorded, COMMIT)[0]
        report["fault"]["anchor"]["x"] = 2
        self.assertTrue(replay_result(report, recorded)["anchorReached"])
        report["fault"]["faultTick"] = 0
        result = replay_result(report, recorded)
        self.assertFalse(result["anomalyReproduced"])
        self.assertEqual(filter_result([result] * 3), "not-reproduced")
        self.assertEqual(filter_result([result] * 2), "incomplete")
        yes = {"anchorReached": True, "anomalyReproduced": True}
        self.assertEqual(filter_result([yes, yes, result]), "not-reproduced")

    def test_incomplete_or_nonfinite_recorded_traces_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.json"
            recorded = trace([{"player": [0, 0]}])
            path.write_text(json.dumps(recorded))
            with self.assertRaises(RouteError):
                read_trace(path, 2, 120)
            recorded["rows"][0]["player"][0] = float("nan")
            path.write_text(json.dumps(recorded))
            with self.assertRaises(RouteError):
                read_trace(path, 1, 120)

    def test_writer_refuses_incomplete_engine_trace_and_unknown_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            (project / "project.godot").write_text('[input]\nmove_right={}\n')

            def replay(_route, dest, **_kwargs):
                dest.mkdir(parents=True)
                (dest / "trace.json").write_text(json.dumps(trace([{"player": [0, 0]}])))

            with mock.patch("harness.run.run", side_effect=replay):
                with self.assertRaises(RouteError):
                    play(project, COMMIT, 0, Path(tmp) / "short", ticks=2)

            def unknown(_route, dest, **_kwargs):
                dest.mkdir(parents=True)
                recorded = trace([{"player": [0, 0]}])
                recorded.update(physicsTicksPerSecond=60, unknownActions=["move_right"])
                (dest / "trace.json").write_text(json.dumps(recorded))

            with mock.patch("harness.run.run", side_effect=unknown):
                with self.assertRaisesRegex(ValueError, "recognise"):
                    play(project, COMMIT, 0, Path(tmp) / "unknown", ticks=1)
            self.assertEqual(list(Path(tmp).glob("*/reports/*.json")), [])

    def test_writer_does_not_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("harness.run.run") as replay:
                with self.assertRaisesRegex(ValueError, "exists"):
                    play(Path(tmp), COMMIT, 0, Path(tmp))
                replay.assert_not_called()


if __name__ == "__main__":
    unittest.main()
