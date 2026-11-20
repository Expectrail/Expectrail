"""The episode clock, using offline Godot- and Unity-shaped captures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from expectrail import observation_timeline
from expectrail.contracts import validate_v1
from expectrail.trace.evaluator import evaluate
from expectrail.trace.normalize import from_run_dir, normalize
from tests.test_observation_timeline import png, trace_at
from tests.test_trace_evaluator import spec


COUNT = spec({"type": "min_event_count", "event": "projectile_spawn", "min": 1}, "projectile")
RESPONSE = spec({"type": "event_response", "trigger": {"action": "shoot", "pressed": True},
                 "response": "projectile_spawn", "withinSeconds": .1, "refractorySeconds": 0}, "projectile")


class EpisodeCaptureClock(unittest.TestCase):
    def capture(self, ticks, *, shot, press, tps=120, fps=60, phase="post-physics-pre-draw"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name)
        frames = self.folder / "frames"
        frames.mkdir()
        self.trace = trace_at(ticks, tps, fps, phase)
        self.trace["capabilities"] = {"projectiles": "complete"}
        for row in self.trace["rows"]:
            row["projectiles"] = [[0, 1, 2]] if row["tick"] >= shot else []
            if phase == "post-draw":
                row["frame"] = row["tick"]
        for n in range(len(ticks)):
            (frames / f"f{n:08d}.png").write_bytes(png(shade=n))
        (self.folder / "trace.json").write_text(json.dumps(self.trace))
        timeline = observation_timeline.build(self.trace, frames)
        self.replay = {"timeline": timeline, "frameSha256": [f["sourceSha256"] for f in timeline["frames"]],
                       "capture": {"fps": fps, "frames": len(ticks), "physicsTicksPerSecond": tps}}
        self.route = {"ticks": ticks[-1] + 1, "events": [{"tick": press, "action": "shoot", "pressed": True}]}

    def episode(self):
        (self.folder / "replay.json").write_text(json.dumps(self.replay))
        ep = from_run_dir(self.folder, self.route, episode_id="clock")
        validate_v1(ep, "episode")
        return ep

    def review(self, check, detail):
        result = evaluate(check, self.episode())
        self.assertEqual(result["result"], "insufficient_observation", result)
        self.assertFalse(result["coverageComplete"])
        self.assertIn(detail, " ".join(result["diagnostics"]))

    def test_between_draws_neither_interval_nor_neighbour_is_a_witness(self):
        self.capture([0, 2, 4, 5], shot=2, press=1)
        self.assertEqual(evaluate(COUNT, self.episode())["result"], "pass")
        self.review(RESPONSE, "tick 1")
        self.trace["rows"][1]["projectiles"] = [[0, 1, 2]]
        ep = normalize(self.trace, self.route, episode_id="trace-only")
        self.assertEqual(evaluate(COUNT, ep)["result"], "insufficient_observation")

    def test_shifted_capture_or_shifted_png_blocks_a_pass(self):
        self.capture([0, 2, 4, 5], shot=2, press=2)
        self.assertEqual(evaluate(RESPONSE, self.episode())["result"], "pass")
        original = copy.deepcopy(self.replay)
        self.replay["timeline"]["frames"][1]["tick"] = 4
        self.review(RESPONSE, "frame 1")
        self.replay = original
        (self.folder / "frames/f00000001.png").write_bytes(png(shade=2))
        self.review(RESPONSE, "frame 1")

    def test_fractional_clock_and_multiple_draws_at_one_tick(self):
        for tps, fps, ticks in [(120, 50, [0, 3, 6, 8, 11]), (50, 60, [0, 1, 1, 2, 3])]:
            with self.subTest(ticks=ticks):
                self.capture(ticks, shot=ticks[1], press=ticks[1], tps=tps, fps=fps)
                ep = self.episode()
                self.assertEqual(ep["frameMapping"], {"protocol": "capture-ticks/v1", "ticks": ticks})
                result = evaluate(COUNT, ep)
                self.assertEqual((result["result"], result["metrics"]["count"]), ("pass", 1))

    def test_unity_fifty_ticks_one_draw_per_tick(self):
        ticks = list(range(50))
        self.capture(ticks, tps=50, fps=50, phase="post-draw", shot=49, press=49)
        ep = self.episode()
        self.assertEqual(ep["frameMapping"]["ticks"], ticks)
        self.assertEqual(evaluate(RESPONSE, ep)["result"], "pass")

    def test_capture_problem_or_missing_manifest_does_not_become_trace_only(self):
        self.capture([1, 3, 5], shot=3, press=3)
        self.replay.pop("timeline")
        self.review(COUNT, "timeline")
        self.replay["timelineProblem"] = "missing frame 1"
        self.review(COUNT, "missing frame 1")

    def test_episode_example_is_the_projection_of_the_two_contract_examples(self):
        folder = Path(__file__).resolve().parents[1] / "contracts/examples"
        trace = (folder / "trace-capture-timeline.json").read_bytes()
        replay = (folder / "replay-timeline.json").read_bytes()
        example = json.loads((folder / "episode-capture-clock.v1.json").read_text())
        ep = normalize(json.loads(trace), {"name": "episode-clock-example", "ticks": 2, "events": []},
                       episode_id=example["id"], replay=json.loads(replay), trace_bytes=trace, replay_bytes=replay)
        validate_v1(example, "episode")
        self.assertEqual(ep, example)

    def test_relaxing_complete_window_never_fills_a_missing_event(self):
        self.capture([0, 2, 4, 5], shot=1, press=0)
        for op in (COUNT, RESPONSE):
            check = copy.deepcopy(op)
            check["evidenceRequirement"]["completeWindow"] = False
            self.review(check, "tick 1")

    def test_a_window_entirely_between_draws_cannot_establish_an_absence(self):
        self.capture([0, 2, 4, 5], shot=4, press=4)
        self.review({**COUNT, "window": {"kind": "ticks", "fromTick": 1, "toTick": 1}}, "ticks 1 to 1")
