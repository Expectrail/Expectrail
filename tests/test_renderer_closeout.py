"""#515: honest local readiness and the normal app's recorded-answer failure path.

No live client, engine, NumPy or Pillow. The app replay is a stand-in that repeats
one public trace row/image; it is not a full replay of kinematic-character.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from expectrail import app_kinematic, recorded, renderer
from expectrail.contracts import digest
from expectrail.orchestrator import engines
from tests import test_app as app_tests
from tests import test_recorded_renderer_drift as drift_tests

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / 'tests/fixtures/recorded-renderer'


class LocalCaptureOutcomeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.samples = self.root / 'docs/run-it/vision'
        self.samples.mkdir(parents=True)

    def write(self, doc):
        (self.samples / 'clean.json').write_text(json.dumps(doc))

    def capture(self, environment=drift_tests.NEW, *, required=False):
        case = drift_tests.CaptureRendererTest('test_checked_in_recordings_match_the_capture_renderer')
        result = unittest.TestResult()
        with mock.patch.object(drift_tests, 'ROOT', self.root), \
             mock.patch('tests.tool_requirements.godot_binary', return_value=Path('/stand-in')), \
             mock.patch('tests.tool_requirements.require_tool'), \
             mock.patch.object(renderer, 'machine', return_value=drift_tests.probe(environment)), \
             mock.patch.dict(os.environ, {'EXPECTRAIL_ENGINE_TESTS': 'required' if required else ''}):
            case.run(result)
        self.assertEqual(result.testsRun, 1)
        self.assertFalse(result.errors, result.errors)
        return result

    def test_local_renderer_or_engine_version_difference_is_named_skip_never_pass(self):
        self.write(drift_tests.answers())
        for environment in (drift_tests.NEW, drift_tests.OLD | {'version': '4.7.2.other-build'}):
            with self.subTest(environment=environment):
                result = self.capture(environment)
                self.assertFalse(result.failures, result.failures)
                self.assertEqual(len(result.skipped), 1)
                reason = result.skipped[0][1]
                for text in ('recorded-renderer-mismatch', 'clean.json', '20.1.2',
                             environment['version'], environment['device'], 'Re-record'):
                    self.assertIn(text, reason)

    def test_local_unknown_provenance_is_named_skip_never_match(self):
        doc = drift_tests.answers(); doc.pop('renderingEnvironments'); self.write(doc)
        result = self.capture(drift_tests.OLD)
        self.assertFalse(result.failures, result.failures)
        self.assertEqual(len(result.skipped), 1)
        for text in ('recorded-renderer-unknown', 'clean.json', 'not recorded', '20.1.2'):
            self.assertIn(text, result.skipped[0][1])

    def test_required_capture_keeps_mismatch_and_unknown_as_failures(self):
        for unknown in (False, True):
            with self.subTest(unknown=unknown):
                doc = drift_tests.answers()
                if unknown: doc.pop('renderingEnvironments')
                self.write(doc)
                result = self.capture(required=True)
                self.assertFalse(result.skipped)
                self.assertEqual(len(result.failures), 1)
                self.assertIn('clean.json', result.failures[0][1])
                self.assertIn('19.1.7', result.failures[0][1])

    def test_empty_or_corrupt_evidence_is_a_failure_even_on_a_different_machine(self):
        for kind in ('empty', 'corrupt', 'corrupt-and-mismatch'):
            with self.subTest(kind=kind):
                for path in self.samples.iterdir(): path.unlink()
                if kind != 'empty': (self.samples / 'bad.json').write_text('{not-json')
                if kind == 'corrupt-and-mismatch': self.write(drift_tests.answers())
                result = self.capture()
                self.assertFalse(result.skipped)
                self.assertEqual(len(result.failures), 1)
                self.assertIn('No checked-in' if kind == 'empty' else 'bad.json', result.failures[0][1])

    def test_known_matching_environment_is_the_only_passing_readiness_result(self):
        self.write(drift_tests.answers())
        for required in (False, True):
            with self.subTest(required=required):
                result = self.capture(drift_tests.OLD, required=required)
                self.assertFalse(result.skipped)
                self.assertFalse(result.failures)


class AppRecordedRendererTest(unittest.TestCase):
    setUp, close, start, http, finished = (app_tests.HTTPTest.setUp, app_tests.HTTPTest.close,
        app_tests.HTTPTest.start, app_tests.HTTPTest.http, app_tests.HTTPTest.finished)

    def test_real_missing_pixel_answer_reaches_app_result_and_report_with_both_versions(self):
        source = self.root / 'source'; (source / 'player').mkdir(parents=True)
        (source / 'project.godot').write_text('[application]\nconfig/name="recorded-renderer-stand-in"\n')
        (source / 'world.tscn').write_text('[gd_scene format=3]\n[node name="Player" type="Node2D"]\n')
        shutil.copyfile(FIXTURES / 'recorded.png', source / 'player/player.png')
        before = app_kinematic.prepare(source, self.root / 'configured-before')
        after = self.root / 'configured-after'; shutil.copytree(before, after)
        facts = json.loads((FIXTURES / 'source.json').read_text())

        def replay(route, game, out, frames):
            ticks = json.loads(route.read_text())['ticks']
            rows = [copy.deepcopy(facts['traceRow']) | {'tick': t, 'frame': t // 2} for t in range(ticks)]
            folder = out / 'frames'; folder.mkdir(parents=True)
            for n in range(ticks // 2):
                shutil.copyfile(FIXTURES / ('replayed.png' if n == 111 else 'recorded.png'),
                                folder / f'f{n:08d}.png')
            (out / 'replay.json').write_text(json.dumps({'format': 'expectrail.replay/v0',
                                                       'engine': drift_tests.NEW}))
            return {'trace': {'rows': rows, 'physicsTicksPerSecond': 120, 'unknownActions': []},
                    'framesDir': folder, 'replaySha256': digest({'standIn': 'frame-111-drift'})}

        self.engine = engines.GodotGate(replay=replay)
        with mock.patch('agents.sam_observations.MetaSamClient', side_effect=AssertionError('live model')), \
             mock.patch('agents.sam_observations.default_client', side_effect=AssertionError('live model')):
            code, job, _ = self.http('POST', '/api/jobs', {'before': str(before), 'after': str(after),
                                                        'projectConfig': True})
            self.assertEqual(code, 201, job)
            result = self.finished(job['id'])
        self.assertEqual(result['state'], 'needs-review', result)
        self.assertIsNotNone(result['report'])
        code, html, _ = self.http('GET', result['report'])
        self.assertEqual(code, 200)
        text = html.decode('utf-8')
        for phrase in ('recorded under llvmpipe LLVM 20.1.2', 'this replay used llvmpipe LLVM 19.1.7', 'not-recorded'):
            self.assertIn(phrase, text)
        # The example copies the existing approved bytes; this test creates no approval.
        self.assertEqual((before / 'checks' / app_kinematic.SPEC.name).read_bytes(), app_kinematic.SPEC.read_bytes())
