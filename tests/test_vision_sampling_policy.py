"""Regression probes for #493: one shared sampling policy and full non-pass refinement."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.sam_observations import SamError, sample
from expectrail import anchored
from expectrail.contracts import validate
from expectrail.evaluator import digest, evaluate
from expectrail.gate import record, verify
from tests.test_anchored_observer import GAME, SPEC, Sees, make_run


class SamplingPolicyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run = make_run(Path(tmp.name), speed=0.3)
        self.run['trace']['unknownActions'] = []
        self.run['engineObservations'] = verify.observations(self.run['trace'], self.run['replaySha256'])
        self.cal = anchored.calibrate(GAME, self.run, Sees(self.run))
        self.assertTrue(self.cal['enabled'])

    def spec(self, kind, **fields):
        spec = copy.deepcopy(SPEC)
        spec['assertion'] = {'type': kind, 'object': 'player', **fields}
        if kind == 'visible':
            spec['objects'].pop('ground')
        return spec

    def look(self, spec, client, every=4):
        seen = anchored.AnchoredObserver(client, self.cal, every=every).look(spec, self.run)
        validate(seen, 'observations')
        return seen

    def judge(self, spec, seen):
        observer = mock.Mock()
        observer.look.return_value = seen
        return verify.judge_run(spec, self.run, rule=record.BOTH, visual=observer,
                                ticks=240, vision_every=4)

    def assert_same_verdict(self, spec, a, b):
        va, vb = evaluate(spec, a), evaluate(spec, b)
        self.assertEqual(va.pop('observations'), {'sha256': digest(a)})
        self.assertEqual(vb.pop('observations'), {'sha256': digest(b)})
        self.assertEqual(va, vb)  # Only the refinement metadata (and its digest) may differ.

    def test_guard_fractional_visible_checks_every_frame_at_stride_four(self):
        class Quarter(Sees):
            def segment_at(self, png, points):
                if int(Path(png).stem[1:]) % 4:
                    self.calls += 1
                    return [None for _ in points]
                return super().segment_at(png, points)
        spec = self.spec('visible', minFraction=0.9)
        full = self.look(spec, Quarter(self.run), every=1)
        client = Quarter(self.run)
        sparse_requested = self.look(spec, client)
        self.assertEqual(client.calls, 120)
        self.assertEqual(sparse_requested, full)
        # The exact guard probe, independent of the anchored notDrawn diagnosis.
        for doc in (full, sparse_requested):
            for frame in doc['frames']:
                frame.pop('notDrawn', None)
        verdict = evaluate(spec, full)
        self.assertEqual(verdict['result'], 'fail')
        self.assertIn('30 of 120', verdict['reason'])
        self.assertEqual(evaluate(spec, sparse_requested), verdict)
        self.assertEqual(self.judge(spec, sparse_requested)['result'], 'fail')

    def test_gate_and_visual_gap_refuse_fractional_pass_from_sparse_observer(self):
        spec = self.spec('visible', minFraction=0.9)
        seen = self.look(spec, Sees(self.run), every=1)
        seen['frames'] = [f for f in seen['frames'] if f['frame'] in sample(list(range(120)), 4)]
        seen['frames'][-1]['objects']['player'] = []
        self.assertEqual(evaluate(spec, seen)['result'], 'pass')  # 30/31 is the unsafe denominator.
        gap = verify.visual_gap(spec, seen, self.run, 240, vision_every=4)
        self.assertIsNotNone(gap)
        self.assertIn('31 of 120', gap)
        self.assertEqual(self.judge(spec, seen)['result'], 'needs-review')

    def test_reaches_refines_every_frame_and_finds_witness_between_samples(self):
        class Between(Sees):
            def segment_at(self, png, points):
                answers = super().segment_at(png, points)
                if int(Path(png).stem[1:]) != 1:
                    for answer in answers:
                        answer['box'][1] -= 2
                        answer['box'][3] -= 2
                return answers
        spec = self.spec('reaches', goal='ground', distancePx=0)
        client = Between(self.run)
        seen = self.look(spec, client)
        full = self.look(spec, Between(self.run), every=1)
        self.assertEqual(client.calls, 120)
        self.assertEqual(seen['frames'], full['frames'])
        self.assertEqual(seen['analysis']['every'], 1)
        self.assertEqual(seen['analysis']['refined'], [i for i in range(120) if i not in sample(list(range(120)), 4)])
        self.assert_same_verdict(spec, seen, full)
        self.assertEqual(evaluate(spec, seen)['result'], 'pass')
        self.assertIn('frame 1', evaluate(spec, seen)['reason'])
        self.assertEqual(self.judge(spec, seen)['result'], 'pass')

    def test_reaches_without_a_witness_fails_only_after_full_refinement(self):
        class Above(Sees):
            def segment_at(self, png, points):
                answers = super().segment_at(png, points)
                for answer in answers:
                    answer['box'][1] -= 2
                    answer['box'][3] -= 2
                return answers
        spec = self.spec('reaches', goal='ground', distancePx=0)
        client = Above(self.run)
        seen = self.look(spec, client)
        self.assertEqual(client.calls, 120)
        self.assertEqual(self.judge(spec, seen)['result'], 'fail')
        seen['frames'] = [f for f in seen['frames'] if f['frame'] % 4 == 0 or f['frame'] == 119]
        result = self.judge(spec, seen)
        self.assertEqual(result['result'], 'needs-review')
        self.assertIn('refin', result['reason'])
        self.assertIn('31 of 120', result['reason'])

    def test_sampled_reaches_witness_remains_a_pass_without_coverage_obligation(self):
        spec = self.spec('reaches', goal='ground', distancePx=0)
        client = Sees(self.run)
        seen = self.look(spec, client)
        self.assertEqual(client.calls, 31)
        self.assertEqual(self.judge(spec, seen)['result'], 'pass')
        spec['coverage'] = {'minFraction': 0.9}
        gap = verify.visual_gap(spec, seen, self.run, 240, vision_every=4)
        self.assertIsNotNone(gap)
        self.assertIn('31 of 120', gap)
        self.assertEqual(self.judge(spec, seen)['result'], 'needs-review')
        full_client = Sees(self.run)
        full = self.look(spec, full_client)
        self.assertEqual(full_client.calls, 120)
        self.assertEqual(self.judge(spec, full)['result'], 'pass')

    def test_sparse_failure_cannot_reject_until_refined_even_if_metadata_says_full(self):
        seen = self.look(SPEC, Sees(self.run), every=1)
        seen['frames'] = [f for f in seen['frames'] if f['frame'] in sample(list(range(120)), 4)]
        seen['frames'][1]['objects']['player'][0]['box'] = [10, 90, 26, 106]
        self.assertEqual(evaluate(SPEC, seen)['result'], 'fail')
        result = self.judge(SPEC, seen)
        self.assertEqual(result['result'], 'needs-review')
        self.assertIn('refin', result['reason'])

    def test_missing_player_refines_and_reports_actual_consecutive_frames(self):
        class Missing(Sees):
            def segment_at(self, png, points):
                self.calls += 1
                return [None for _ in points]
        client = Missing(self.run)
        seen = self.look(SPEC, client)
        self.assertEqual(client.calls, 120)
        result = self.judge(SPEC, seen)
        self.assertEqual(result['result'], 'fail')
        self.assertIn('frames 0, 1, 2', result['reason'])
        self.assertNotIn('consecutive samples', result['reason'])
        self.assert_same_verdict(SPEC, seen, self.look(SPEC, Missing(self.run), every=1))

    def test_three_isolated_negative_samples_do_not_become_consecutive_missing_frames(self):
        class Isolated(Sees):
            def segment_at(self, png, points):
                if int(Path(png).stem[1:]) in (0, 4, 8):
                    self.calls += 1
                    return [None for _ in points]
                return super().segment_at(png, points)
        client = Isolated(self.run)
        seen = self.look(SPEC, client)
        self.assertEqual(client.calls, 120)
        self.assert_same_verdict(SPEC, seen, self.look(SPEC, Isolated(self.run), every=1))
        result = self.judge(SPEC, seen)
        self.assertEqual(result['result'], 'needs-review')
        self.assertNotIn('did not find player drawn', result['reason'])

    def test_refinement_provider_error_is_needs_review_not_sampled_failure(self):
        class Stops(Sees):
            def segment_at(self, png, points):
                if int(Path(png).stem[1:]) == 1:
                    raise SamError('unavailable', kind='credit')
                return [None for _ in points]
        observer = anchored.AnchoredObserver(Stops(self.run), self.cal, every=4)
        result = verify.judge_run(SPEC, self.run, rule=record.BOTH, visual=observer,
                                  ticks=240, vision_every=4)
        self.assertEqual(result['result'], 'needs-review')
        self.assertIn('credit', result['reason'])
