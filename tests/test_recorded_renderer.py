"""Rendering provenance and exact replay answers (#515); no engine, model or network."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.sam_observations import SamError
from expectrail import anchored, recorded, runit
from expectrail.gate import anchor, verify
from tests import test_runit as runit_tests
from tests import test_two_observers as observers_tests

try:  # only the two pixel-measurement tests need these; the stock CI runner has neither
    import numpy  # noqa: F401
    from PIL import Image
    from tools import recorded_renderer as measurement
except ImportError:
    Image = measurement = None
PIXELS = unittest.skipUnless(measurement, 'numpy and PIL are needed to measure pixels')

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / 'tests/fixtures/recorded-renderer'
RECORDING = ROOT / 'tests/outside/recordings/kinematic-character/vision-recording.json'
OLD = json.loads((FIXTURES / 'recorded-replay.json').read_text())['engine']
NEW = json.loads((FIXTURES / 'replayed-replay.json').read_text())['engine']
POINT = [(488, 329)]


class Answers:
    model, provider = 'stand-in', 'offline'

    def segment_at(self, png, points):
        return [{'box': [481, 321, 497, 337], 'score': .9} for _ in points]


class RenderingTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.frames = self.root / 'frames'
        self.frames.mkdir()
        self.png = self.frames / 'f00000111.png'
        self.doc = recorded.read_recording(RECORDING)

    def capture(self, image='recorded.png', environment=OLD):
        shutil.copyfile(FIXTURES / image, self.png)
        (self.root / 'replay.json').write_text(json.dumps({'format': 'expectrail.replay/v0', 'engine': environment}))
        return self.png

    def assert_mismatch(self, exc):
        self.assertIn('recorded under llvmpipe LLVM 20.1.2', str(exc))
        self.assertIn('this replay used llvmpipe LLVM 19.1.7', str(exc))
        self.assertIn('not-recorded', str(exc))

    def test_writer_round_trip_names_captures_not_the_judges_environment(self):
        client = recorded.RecordingClient(Answers())
        client.segment_at(self.capture(), POINT)
        client.segment_at(self.capture('replayed.png', NEW), POINT)
        doc = client.recording(sample='example', recorded_at='2026-11-15', run='offline-test')
        self.assertCountEqual(doc['renderingEnvironments'], [OLD, NEW])
        path = recorded.write_recording(self.root / 'answers.json', doc)
        reader = recorded.RecordedClient(recorded.read_recording(path))
        self.assertEqual(reader.segment_at(self.png, POINT), Answers().segment_at(self.png, POINT))
        self.assertEqual(reader.answered, 1)

    def test_new_writer_explicitly_records_unknown_when_capture_is_absent(self):
        shutil.copyfile(FIXTURES / 'recorded.png', self.png)
        client = recorded.RecordingClient(Answers())
        client.segment_at(self.png, POINT)
        doc = client.recording(sample='unknown', recorded_at='2026-11-15', run='offline')
        self.assertEqual(doc['renderingEnvironments'], [None])
        recorded.check(doc)

    def test_old_recordings_stay_readable_and_do_not_guess_an_environment(self):
        self.doc.pop('renderingEnvironments')
        client = recorded.RecordedClient(self.doc)
        self.assertEqual(len(client.segment_at(self.capture(), POINT)), 1)
        with self.assertRaises(SamError) as caught:
            client.segment_at(self.capture('replayed.png', NEW), POINT)
        self.assertEqual(caught.exception.kind, 'not-recorded')
        self.assertNotIn('recorded under', str(caught.exception))

    def test_missing_image_names_both_renderer_versions(self):
        client = recorded.RecordedClient(self.doc)
        with self.assertRaises(SamError) as caught:
            client.segment_at(self.capture('replayed.png', NEW), POINT)
        self.assert_mismatch(caught.exception)
        self.assertEqual(client.answered, 0)
        self.assertEqual(client.last_missing_reason, str(caught.exception))

    def test_same_image_in_another_environment_still_uses_exact_answer(self):
        client = recorded.RecordedClient(self.doc)
        self.assertEqual(client.segment_at(self.capture(environment=NEW), POINT)[0]['box'], [481., 321., 497., 337.])
        self.assertEqual((client.calls, client.answered, client.not_recorded), (1, 1, 0))

    def test_missing_question_for_known_image_is_not_blamed_on_renderer(self):
        with self.assertRaises(SamError) as caught:
            recorded.RecordedClient(self.doc).segment_at(self.capture(environment=NEW), [(0, 0)])
        self.assertNotIn('recorded under', str(caught.exception))

    def test_same_or_unknown_environment_does_not_claim_renderer_difference(self):
        for env in [OLD, {}, {'name': 'godot', 'version': OLD['version']}]:
            with self.subTest(env=env), self.assertRaises(SamError) as caught:
                recorded.RecordedClient(self.doc).segment_at(self.capture('replayed.png', env), POINT)
            self.assertNotIn('recorded under', str(caught.exception))

    def test_invalid_linked_or_oversized_capture_is_unknown(self):
        self.capture()
        path = self.root / 'replay.json'
        for raw in ['{', '[]', '{"format":"wrong","engine":{}}']:
            path.write_text(raw)
            self.assertIsNone(recorded.capture_environment(self.png))
        path.unlink()
        path.symlink_to(FIXTURES / 'recorded-replay.json')
        self.assertIsNone(recorded.capture_environment(self.png))
        path.unlink()
        path.write_bytes(b' ' * (recorded.MAX_BYTES+1))
        self.assertIsNone(recorded.capture_environment(self.png))

    def test_example_and_provenance_fields_are_validated(self):
        recorded.check(json.loads((ROOT / 'contracts/examples/vision-recording.json').read_text()))
        for environments in ['unknown', [{}], [{**OLD, 'device': 'line\nbreak'}], [{**OLD, 'extra': True}],
                             [{**OLD, 'version': 'x' * 161}], [OLD] * 33]:
            with self.subTest(environments=environments), self.assertRaises(recorded.RecordingError):
                recorded.check({**self.doc, 'renderingEnvironments': environments})

    def test_bank_retains_all_environments_without_false_mismatch(self):
        other = copy.deepcopy(self.doc)
        other.update(sample='other', renderingEnvironments=[NEW], answers=[])
        observer = recorded.RecordedBankObserver([self.doc, other])
        with self.assertRaises(SamError) as caught:
            observer.client.segment_at(self.capture('replayed.png', NEW), POINT)
        self.assertNotIn('recorded under', str(caught.exception))
        self.assertCountEqual(observer.client._environments, [OLD, NEW])
        observer = recorded.RecordedBankObserver([self.doc, {**other, 'renderingEnvironments': [None]}])
        with self.assertRaises(SamError) as caught:
            observer.client.segment_at(self.png, POINT)
        self.assertNotIn('recorded under', str(caught.exception))

    def test_engine_or_renderer_changes_are_explained_too(self):
        for key, value in [('version', '4.8'), ('renderer', 'vulkan'), ('name', 'other-engine')]:
            with self.subTest(key=key), self.assertRaises(SamError) as caught:
                recorded.RecordedClient(self.doc).segment_at(self.capture('replayed.png', {**OLD, key: value}), POINT)
            self.assertIn(value, str(caught.exception))
            self.assertIn(OLD[key], str(caught.exception))

    def test_long_driver_name_keeps_the_differing_version_visible(self):
        common = 'Example graphics driver ' * 3
        doc = {**self.doc, 'renderingEnvironments': [{**OLD, 'device': common+'100.1'}]}
        with self.assertRaises(SamError) as caught:
            recorded.RecordedClient(doc).segment_at(self.capture('replayed.png', {**OLD, 'device': common+'100.2'}), POINT)
        self.assertIn('100.1', str(caught.exception))
        self.assertIn('100.2', str(caught.exception))

    def test_same_llvm_version_does_not_hide_another_device_difference(self):
        changed = {**OLD, 'device': OLD['device'].replace('256 bits', '512 bits')}
        with self.assertRaises(SamError) as caught:
            recorded.RecordedClient(self.doc).segment_at(self.capture('replayed.png', changed), POINT)
        self.assertIn('256 bits', str(caught.exception))
        self.assertIn('512 bits', str(caught.exception))

    def run_doc(self):
        source = json.loads((FIXTURES / 'source.json').read_text())
        return {'trace': {'rows': [source['traceRow']] * 224,
                          'physicsTicksPerSecond': source['physicsTicksPerSecond']},
                'framesDir': self.frames, 'replaySha256': 'a' * 64}

    def test_anchored_wrapper_preserves_reason_and_original_answer(self):
        calibration = json.loads((RECORDING.parent / 'calibration.json').read_text())
        spec = {'objects': {'player': {'prompt': 'player'}}, 'assertion': {'object': 'player'}, 'window': {'fromFrame': 111, 'toFrame': 111}}
        observer = recorded.with_recorded_diagnostics(anchored.AnchoredObserver(recorded.RecordedClient(self.doc), calibration))
        self.capture()
        seen = observer.look(spec, self.run_doc())
        self.assertEqual(seen['frames'][0]['objects']['player'][0]['box'], [481., 321., 497., 337.])
        self.capture('replayed.png', NEW)
        with self.assertRaises(verify.NoAnswer) as caught:
            observer.look(spec, self.run_doc())
        self.assert_mismatch(caught.exception)

    def test_anchor_comparison_keeps_reason_when_both_sides_have_no_answer(self):
        self.capture('replayed.png', NEW)
        result = anchor.compare('walk', self.run_doc(), self.run_doc(), recorded.RecordedClient(self.doc))
        self.assertEqual(result['result'], 'no-answer')
        self.assertEqual(result['noAnswer'], 1)
        block = anchor.block([('walk', self.run_doc(), self.run_doc())], recorded.RecordedClient(self.doc), None)
        self.assertEqual(block['routes'][0]['result'], 'no-answer')
        self.assertEqual(block['routes'][0]['noAnswer'], 1)
        self.assertIn('LLVM 20.1.2', result['reason'])
        self.assertIn('LLVM 19.1.7', result['reason'])

    def test_model_error_bodies_are_never_promoted_to_public_reasons(self):
        class Broken:
            def look(self, *args, **kwargs):
                try:
                    raise SamError('secret provider error body', kind='network')
                except SamError as exc:
                    raise verify.NoAnswer('the model did not answer (network)') from exc
        with self.assertRaises(verify.NoAnswer) as caught:
            recorded.with_recorded_diagnostics(Broken()).look({}, {})
        self.assertNotIn('secret', str(caught.exception))
        self.assertIsNone(recorded.missing_reason(caught.exception))

    @PIXELS
    def test_measured_visual_changes_never_reuse_the_clean_frame_answer(self):
        reference, box, cases = measurement.cases()
        sha = json.loads((FIXTURES / 'source.json').read_text())['hashes']['recorded.png']
        clean = {**self.doc, 'answers': [a for a in self.doc['answers'] if a['frameSha256'] == sha]}
        for name, pixels, _ in cases:
            with self.subTest(case=name):
                Image.fromarray(pixels).save(self.png)
                with self.assertRaises(SamError) as caught:
                    recorded.RecordedClient(clean).segment_at(self.png, POINT)
                self.assertEqual(caught.exception.kind, 'not-recorded')
        self.assertEqual(measurement.metrics(reference, reference, box)['changedPixels'], 0)

    @PIXELS
    def test_published_measurements_reproduce_and_overlap_is_explicit(self):
        doc = measurement.measure()
        self.assertEqual(doc, json.loads((ROOT / 'docs/measurements/recorded-renderer.json').read_text()))
        self.assertEqual(doc['differentFrames'], [111])
        self.assertEqual(doc['identicalFrames'], 179)
        rows = {r['case']: r for r in doc['rows']}
        for key in ['changedPixels', 'largestChannelDifference']:
            self.assertEqual(rows['renderer-frame-111'][key], rows['two-player-pixels-one-level'][key])
        self.assertGreater(rows['renderer-frame-111']['nearestPlayerDistancePx'], 261)
        self.assertEqual(rows['two-player-pixels-one-level']['nearestPlayerDistancePx'], 0)


class GatePathTest(unittest.TestCase):
    def test_runit_records_environment_and_missing_answer_reaches_status_and_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = runit_tests.make_root(root / 'repo')
            game = observers_tests.Game()
            drift = False
            def replay(route, project, out, frames):
                run = game.replay(route, project, out, frames)
                (out / 'replay.json').write_text(json.dumps({'format': 'expectrail.replay/v0', 'engine': NEW if drift else OLD}))
                if drift:
                    # Different bytes, not a live model call or a loosened matcher.
                    from tests.test_sam import png_bytes
                    (out / 'frames/f00000111.png').write_bytes(png_bytes(64, 64, 515))
                return run
            target = repo / 'docs/run-it/vision/clean.json'
            with contextlib.redirect_stdout(io.StringIO()):
                runit.record('clean', target, root=repo, client=game.observer()._client,
                             replay=replay, run_id='offline', recorded_at='2026-11-15')
                self.assertEqual(recorded.read_recording(target)['renderingEnvironments'], [OLD])
                clean = runit.run('clean', root / 'clean', root=repo, replay=replay, request_id='clean')
                self.assertEqual(clean['decision'], 'accept')
                drift = True
                with mock.patch('agents.sam_observations.default_client', side_effect=AssertionError('live model')):
                    result = runit.run('clean', root / 'drift', root=repo, replay=replay, request_id='drift')
            self.assertEqual(result['decision'], 'needs-review')
            findings = json.loads((root / 'drift/findings.json').read_text())
            self.assertIn('LLVM 20.1.2', json.dumps(findings['findings']))
            self.assertIn('LLVM 19.1.7', json.dumps(findings['findings']))
            self.assertIn('LLVM 19.1.7', result['vision']['why'])
