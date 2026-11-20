"""Read-only engine setup reports, including projects without optional image packages.

Guard: test change intended (#260)
Reason: add coverage for the missing runtime commands and strict measurement reader;
existing assertions and approval records are unchanged.
"""
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents import unity_observations as uo
from expectrail import cli, contracts, onboarding, project_config
from tests import cli_capture

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'tests/projects/config-lane'


def command(*args):
    output = io.StringIO()
    with cli_capture.command_output(output):
        code = cli.main([str(a) for a in args])
    return code, output.getvalue()


def measurements():
    return [dict(frame=0, tick=1, playerBoxes=[[10, 20, 34, 44]], coinBoxes=[], ground=44, onFloor=True),
            dict(frame=1, tick=3, playerBoxes=[[10, 10, 34, 34]], coinBoxes=[[0, 0, 8, 8]], ground=44, onFloor=False)]


def report():
    return {'format': 'expectrail.setup-report/v1',
            'source': {'gameTreeSha256': 'a'*64, 'configSha256': 'b'*64, 'routeSha256': 'c'*64,
                       'routeTicks': 4, 'physicsTicksPerSecond': 120, 'captureFps': 60,
                       'viewport': [360, 240], 'entryScene': 'res://main.tscn', 'bindingRoles': ['player']},
            'runs': [{'replaySha256': 'd'*64, 'traceSha256': 'e'*64, 'engineVersion': '4.7.2.stable'} for _ in range(3)],
            'calibration': uo.calibrate({}, measured=measurements()),
            'stability': {'identical': True, 'changedTicks': [], 'changedHeaders': []}}


class CalibrationNumbersTest(unittest.TestCase):
    def test_explicit_measurements_have_hand_computed_sizes_gaps_and_counts(self):
        data = uo.calibrate({}, measured=measurements())
        self.assertEqual(data['rows'], 2)
        self.assertEqual(data['playerVisible'], 2)
        self.assertEqual(data['playerWidth'], dict(n=2, min=24, median=24.0, max=24))
        self.assertEqual(data['playerHeight'], dict(n=2, min=24, median=24.0, max=24))
        self.assertEqual(data['onFloorBottomMinusGround'], dict(n=1, min=0, median=0, max=0))
        self.assertEqual(data['airborneBottomMinusGround'], dict(n=1, min=-10, median=-10, max=-10))
        self.assertEqual(data['coinsVisiblePerFrame'], dict(n=2, min=0.0, median=0.5, max=1.0))
        self.assertEqual(data['coinWidth'], dict(n=1, min=8, median=8, max=8))
        self.assertEqual(data['unjudgeableRows'], 0)

    def test_unknown_floor_and_missing_ground_are_not_airborne(self):
        frames = measurements()
        frames[0]['onFloor'] = None
        frames[1]['ground'] = None
        data = uo.calibrate({}, measured=frames)
        self.assertEqual(data['unjudgeableRows'], 2)
        self.assertEqual([x['reasons'] for x in data['unjudgeable']],
                         [['floor-state-unavailable'], ['ground-unavailable']])
        self.assertIsNone(data['airborneBottomMinusGround'])
        self.assertIsNone(data['onFloorBottomMinusGround'])

    def test_ambiguous_player_is_not_silently_the_first_player(self):
        frames = measurements()
        frames[0]['playerBoxes'] *= 2
        frames[1]['playerBoxes'] = []
        data = uo.calibrate({}, measured=frames)
        self.assertEqual(data['playerSeveral'], 1)
        self.assertEqual(data['unjudgeableRows'], 2)
        self.assertIsNone(data['playerWidth'])

    def test_legacy_unity_mode_is_byte_identical(self):
        # Compare actual main implementation on a nonempty trace, not a copied expectation.
        import importlib.util
        source = subprocess.run(['git', 'show', 'HEAD:agents/unity_observations.py'], cwd=ROOT,
                                check=True, capture_output=True, text=True).stdout
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'legacy.py'; path.write_text(source)
            spec = importlib.util.spec_from_file_location('legacy_setup_calibration', path)
            legacy = importlib.util.module_from_spec(spec); spec.loader.exec_module(legacy)
            trace = {'rows': [{'tick': i, 'onFloor': i % 2 == 0, 'ground': 100,
                              'player': [20, 80], 'view': [1, 0, 0, 1, 0, 0]} for i in range(4)]}
            self.assertEqual(json.dumps(uo.calibrate(trace)), json.dumps(legacy.calibrate(trace)))


class ReportReaderTest(unittest.TestCase):
    def test_schema_and_semantic_reader_round_trip(self):
        doc = report()
        contracts.validate_v1(doc, 'setup-report')
        onboarding.check_setup_report(doc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'report.json'; path.write_text(json.dumps(doc))
            self.assertEqual(onboarding.read_setup_report(path), doc)

    def test_refuses_laundered_statistics_missing_frames_and_false_stability(self):
        for name in ('median', 'frame', 'runs', 'hash', 'stability', 'rate', 'nan'):
            with self.subTest(name=name):
                doc = report()
                if name == 'median': doc['calibration']['playerWidth']['median'] = 100
                if name == 'frame': doc['calibration']['frameMeasurements'].pop()
                if name == 'runs': doc['runs'].pop()
                if name == 'hash': doc['runs'][1]['traceSha256'] = 'f'*64
                if name == 'stability': doc['stability']['changedTicks'] = [1]
                if name == 'rate': doc['source']['captureFps'] = 59
                if name == 'nan': doc['calibration']['playerWidth']['median'] = float('nan')
                with self.assertRaises(ValueError): onboarding.check_setup_report(doc)

    def test_committed_example_is_a_readable_real_engine_report(self):
        doc = onboarding.read_setup_report(ROOT/'contracts/examples/setup-report.json')
        contracts.validate_v1(doc, 'setup-report')
        self.assertEqual(doc['source']['viewport'], [360, 240])
        self.assertEqual(doc['calibration']['rows'], 120)

    def test_duplicate_keys_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'report.json'; path.write_text('{"format":"a","format":"b"}')
            with self.assertRaises(ValueError): onboarding.read_setup_report(path)


class SetupErrorsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.game = Path(self.tmp.name)/'game'; shutil.copytree(GAME, self.game)

    def test_missing_engine_names_the_command_to_fix_it(self):
        code, text = command('calibrate', self.game, '--route', 'walk.json', '--godot', '/missing/engine')
        self.assertEqual(code, 5, text)
        self.assertIn('--godot PATH', text)
        self.assertIn('4.7.2', text)

    def test_similar_but_wrong_engine_version_is_refused(self):
        for version in ('4.7.2.stable-wrong', '4.7.1.stable.official'):
            with self.subTest(version=version), mock.patch('subprocess.run',
                    return_value=mock.Mock(returncode=0, stdout=version)):
                with self.assertRaisesRegex(ValueError, '--godot PATH'):
                    onboarding._local_engine(self.game/'project.godot')

    def test_bad_routes_name_route_and_correction_before_replay(self):
        for doc in ({}, {'format': 'expectrail.route/v0', 'name': 'bad', 'seed': 1, 'ticks': 2,
                         'events': [{'tick': 0, 'action': 'unknown', 'pressed': True}]}):
            path = self.game/'bad.json'; path.write_text(json.dumps(doc))
            code, text = command('calibrate', self.game, '--route', 'bad.json', '--godot', '/missing')
            self.assertEqual(code, 5, text)
            self.assertIn('route', text)
            self.assertTrue('Fix' in text or 'fix' in text, text)
            self.assertNotIn('No engine was downloaded', text)

    def test_evidence_never_overwrites_or_changes_project(self):
        for out in (self.game, self.game/'new', Path(self.tmp.name)):
            code, text = command('calibrate', self.game, '--route', 'walk.json', '--out', out)
            self.assertEqual(code, 5, text)
            self.assertIn('new --out folder outside the project', text)
        self.assertFalse((self.game/'new').exists())

    def test_invalid_tick_has_named_fix(self):
        code, text = command('inspect', self.game, '--at-tick', -1)
        self.assertEqual(code, 5, text)
        self.assertIn('--at-tick', text)

    def test_a_route_longer_than_the_setup_bound_names_it(self):
        route = self.game/'long.json'
        route.write_text(json.dumps({'format': 'expectrail.route/v0', 'name': 'long', 'seed': 1,
                                     'ticks': 7201, 'events': []}))
        code, text = command('calibrate', self.game, '--route', 'long.json')
        self.assertEqual(code, 5, text)
        self.assertIn('7200', text)

    def test_nondivisor_physics_rate_proposes_a_valid_capture_rate(self):
        settings = self.game/'project.godot'
        settings.write_text(settings.read_text().replace('common/physics_ticks_per_second=60',
                                                         'common/physics_ticks_per_second=45'))
        code, text = command('init', self.game, '--dry-run')
        self.assertEqual(code, 0, text)
        config = json.loads(text)['config']
        self.assertEqual(config['physicsTicksPerSecond'], 45)
        self.assertEqual(config['captureFps'], 45)

    def test_invalid_capture_rate_names_both_config_settings(self):
        path = self.game/'expectrail.project.json'
        config = json.loads(path.read_text()); config['captureFps'] = 59
        path.write_text(json.dumps(config))
        code, text = command('calibrate', self.game, '--route', 'walk.json')
        self.assertEqual(code, 5, text)
        for word in ('captureFps', 'physicsTicksPerSecond', 'expectrail.project.json'):
            self.assertIn(word, text)

    def test_unstable_calibration_prints_report_and_refuses_success(self):
        doc = report(); doc['stability']['identical'] = False
        doc['stability']['changedTicks'] = [1]; doc['runs'][1]['traceSha256'] = 'f'*64
        with mock.patch.object(onboarding, 'runtime_setup', return_value=doc):
            code, text = command('calibrate', self.game, '--route', 'walk.json')
        self.assertEqual(code, 5, text)
        self.assertIn('False', text)
        self.assertIn('coins visible a frame', text)
        self.assertIn('Fix replay nondeterminism', text)

    def test_import_and_numbers_without_numpy_or_pillow(self):
        script = """import sys, importlib.abc
class NoExtras(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, *args):
  if fullname.split('.')[0] in ('numpy','PIL'): raise ImportError('extras deliberately absent')
sys.meta_path.insert(0,NoExtras())
from expectrail import onboarding
from agents.unity_observations import calibrate
assert calibrate({}, measured=[])['unjudgeableRows'] == 0
"""
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class EngineSetupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.tool_requirements import godot_binary
        cls.engine = godot_binary()

    def test_three_clean_runs_have_expected_dimensions_and_are_identical(self):
        doc = onboarding.runtime_setup(GAME, route_path='walk.json', godot=self.engine)
        onboarding.check_setup_report(doc)
        self.assertTrue(doc['stability']['identical'])
        c = doc['calibration']
        self.assertEqual(c['rows'], 120)
        self.assertEqual(c['playerVisible'], 120)
        self.assertEqual(c['playerWidth'], dict(n=120, min=24, median=24.0, max=24))
        self.assertEqual(c['unjudgeableRows'], 0)
        self.assertEqual(c['onFloorBottomMinusGround'], dict(n=120, min=-0.075, median=-0.075, max=-0.075))
