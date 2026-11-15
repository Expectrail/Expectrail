"""Arithmetic and byte-only exclusions for the frozen #262 measurement; no pixels/model."""
import unittest
from tools.template_untuned_measure import selected_frames,totals


class MeasurementCountsTest(unittest.TestCase):
    def test_callback_binds_to_the_frozen_sensor_api_before_any_pixel_is_opened(self):
        import inspect
        from agents import template_observations as sensor
        inspect.signature(sensor.from_replay).bind({},replay_sha256='a'*64,frames_dir='unused',
            bank={},spec={},fps=60,on_frame=lambda frame,seconds:None)

    def test_prior_pixels_are_excluded_by_hash_not_by_sensor_outcome(self):
        self.assertEqual(selected_frames(['old','new','new','cal'],{'old','cal'}),[1,2])

    def test_presence_and_crossing_are_counted_once_and_unknown_is_not_a_pass(self):
        result=totals({0:'matched',1:'not-found',2:'out-of-frame',3:'displaced'},range(4),[1,3],[1,2])
        self.assertEqual((result['alarms'],result['measured'],result['offscreen']),(2,3,1))
        self.assertEqual(result['falseAlarmRate'],2/3)
        self.assertFalse(result['eligibleForLaterConsideration'])

    def test_absent_floor_reference_cannot_certify_the_whole_sensor(self):
        result=totals({0:'matched'},[0],region_applicable=False)
        self.assertEqual(result['falseAlarmRate'],0)
        self.assertEqual(result['regionUnavailable'],1)
        self.assertFalse(result['eligibleForLaterConsideration'])
