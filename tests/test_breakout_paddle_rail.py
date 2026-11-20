"""The public Breakout draft should catch a displaced paddle drawing during play."""
import json
import unittest
from pathlib import Path

from expectrail.evaluator import evaluate
from expectrail.gate.verify import observations, window_frames


ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / 'docs/outside-trials/breakout-ci/traces/breakout/draft-diagnostics/pointer-auto/trace.json'
DRAFT = ROOT / 'tests/outside/breakout-pointer/checks/breakout-paddle-bounds.json'


class BreakoutPaddleRailTest(unittest.TestCase):
    def test_a_drawing_displaced_off_the_rail_fails_inside_the_viewport(self):
        spec = json.loads(DRAFT.read_bytes())
        trace = json.loads(TRACE.read_bytes())
        obs = observations(trace, '0' * 64)
        context = {
            'trace': trace, 'route': 'auto-input-map', 'capture_fps': 60,
            'expected_frames': window_frames(spec, trace['ticks'], trace, 60),
        }
        self.assertEqual(evaluate(spec, obs, **context)['result'], 'pass')
        frame = next(frame for frame in obs['frames'] if frame['frame'] == 35)
        player = frame['objects']['player'][0]
        x0, y0, x1, y1 = player['box']
        for displacement in (-2, 2):
            with self.subTest(displacement=displacement):
                player['box'] = [x0, y0 + displacement, x1, y1 + displacement]
                result = evaluate(spec, obs, **context)
                self.assertEqual((result['result'], result['firstFrame']), ('fail', 35))
