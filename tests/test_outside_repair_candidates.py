"""A rehearsal result must demonstrate each named public repair control."""
import copy
import unittest

from tests.outside import repair_pair


def completed(decision, engine, visual):
    return {'phase': 'completed', 'decision': decision,
            'isolation': {'required': True, 'sandboxed': 2, 'replays': 2},
            'checks': [{'spec': 'player-stays-above-ground', 'route': 'walk',
                        'observed': {'after': {'engine': engine, 'visual': visual}}}]}


class RepairControlsTest(unittest.TestCase):
    def setUp(self):
        self.rows = {'mask-2': completed('reject', 'fail', 'not-asked'),
                     'hidden-sprite': completed('needs-review', 'needs-review', 'no-answer'),
                     'stuck-fade': completed('reject', 'pass', 'fail'),
                     'restored': completed('accept', 'pass', 'pass')}

    def test_matching_controls_pass_without_pinning_the_mask_visual_or_frame(self):
        self.rows['mask-2']['checks'][0]['observed']['after']['visual'] = 'fail'
        self.assertEqual(repair_pair.unmet_controls(self.rows), [])

    def test_unexpected_verdict_on_each_candidate_reports_its_name_and_keeps_the_output(self):
        for name in self.rows:
            with self.subTest(name=name):
                rows = copy.deepcopy(self.rows)
                rows[name]['decision'] = 'needs-review' if name == 'restored' else 'accept'
                original = copy.deepcopy(rows)
                self.assertIn(name, ' '.join(repair_pair.unmet_controls(rows)))
                self.assertEqual(rows, original)

    def test_wrong_route_or_missing_observers_cannot_satisfy_a_control(self):
        for name in ('hidden-sprite', 'stuck-fade', 'restored'):
            for changed in ({'route': 'other'}, {'spec': 'other'}, {'observed': {}},
                            {'observed': {'after': {'engine': 'fail', 'visual': 'not-asked'}}}):
                with self.subTest(name=name, changed=changed):
                    rows = copy.deepcopy(self.rows)
                    rows[name]['checks'][0].update(changed)
                    self.assertIn(name, ' '.join(repair_pair.unmet_controls(rows)))

    def test_inconclusive_visibility_cannot_substitute_for_a_rejected_fade(self):
        self.rows['stuck-fade'] = copy.deepcopy(self.rows['hidden-sprite'])
        misses = repair_pair.unmet_controls(self.rows)
        self.assertTrue(any('stuck-fade' in message for message in misses))
        self.assertFalse(any('hidden-sprite' in message for message in misses))

    def test_incomplete_or_unisolated_replay_or_missing_candidate_is_reported(self):
        for changed in ({'phase': 'failed'}, {'checks': []}, {'isolation': None},
                        {'isolation': {'required': True, 'sandboxed': 0, 'replays': 0}},
                        {'isolation': {'required': True, 'sandboxed': 1, 'replays': 2}},
                        {'isolation': {'required': False, 'sandboxed': 2, 'replays': 2}}):
            with self.subTest(changed=changed):
                rows = copy.deepcopy(self.rows)
                rows['mask-2'].update(changed)
                self.assertIn('mask-2', ' '.join(repair_pair.unmet_controls(rows)))
        del self.rows['hidden-sprite']
        self.assertIn('hidden-sprite', ' '.join(repair_pair.unmet_controls(self.rows)))
