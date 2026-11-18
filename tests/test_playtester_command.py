"""The producer uses the merged report reader and preserves product intake distinctions."""
import copy
import importlib.abc
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools.playtester.command import classify, compact, environment, groups, ingest
from tools.playtester.command import write_report, report_documents, play
from tools.playtester import producer


def report(name='report-one', x=0):
    return {'format': 'expectrail.playtest-report/v1', 'id': name,
            'producer': {'name': 'Expectrail', 'version': '1'}, 'target': {'commit': 'a'*40},
            'route': {'format': 'expectrail.route/v0', 'name': 'example', 'ticks': 3, 'events': []},
            'bug': 'My character stops moving.', 'fault': {'preFaultTick': 0, 'faultTick': 1,
            'anchor': {'object': 'player', 'x': x, 'y': 10, 'tolerancePx': 2}}}


class CommandTest(unittest.TestCase):
    def trace_fixture(self):
        route = {'format': 'expectrail.route/v0', 'name': 'adapter-route', 'ticks': 12,
                 'events': [{'tick': 0, 'action': 'move_right', 'pressed': True},
                            {'tick': 11, 'action': 'move_right', 'pressed': False}]}
        trace = {'rows': [{'tick': i, 'player': [2*i, 10], 'facing': 1 if i % 2 == 0 else -1}
                          for i in range(12)], 'levelSurfaces': [[[0, 100], [100, 100]]]}
        return route, trace

    def test_adapter_preserves_main_observation_and_route_without_mutating_legacy_reports(self):
        route, trace = self.trace_fixture()
        legacy = producer.reports(route, trace, 'a'*40)
        before = copy.deepcopy(legacy)
        self.assertEqual(len(legacy), 1)
        self.assertEqual(legacy[0]['fault']['anchor']['object'], 'Player')
        with mock.patch.object(producer, 'reports', return_value=legacy):
            docs = report_documents(route, trace, 'a'*40)
            self.assertEqual(docs, report_documents(route, trace, 'a'*40))
        self.assertEqual(legacy, before)
        self.assertEqual(docs[0]['route'], route)
        self.assertEqual(docs[0]['bug'], legacy[0]['bug'])
        self.assertEqual(docs[0]['fault']['faultTick'], legacy[0]['fault']['faultTick'])
        self.assertEqual(docs[0]['fault']['anchor']['object'], 'player')
        self.assertEqual(docs[0]['producer']['version'], producer.VERSION + '+ingest.1')
        self.assertNotEqual(docs[0]['id'], legacy[0]['id'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'report.json'; write_report(path, docs[0])
            from expectrail.orchestrator.playtest import load
            self.assertEqual(load(path), docs[0])

    def test_adapter_does_not_guess_unknown_uppercase_object_names(self):
        bad = report();bad['fault']['anchor']['object'] = 'UnknownRole'
        with mock.patch.object(producer, 'reports', return_value=[bad]):
            with self.assertRaises(ValueError):report_documents({}, {}, 'a'*40)

    def test_play_writes_only_adapted_contract_valid_documents(self):
        route, trace = self.trace_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);out = root/'discovery'
            with mock.patch('expectrail.route.input_map', return_value=(['move_right'],120,{})), \
                 mock.patch('expectrail.route.read_trace', return_value=trace), \
                 mock.patch.object(producer,'make_route',return_value=route) as make, \
                 mock.patch('harness.run.run') as run:
                docs=play(root/'project','a'*40,10000,out,ticks=12,godot=Path('/pinned-godot'))
            make.assert_called_once_with(['move_right'],10000,12)
            self.assertEqual(run.call_args.kwargs['godot'],Path('/pinned-godot'))
            self.assertFalse(run.call_args.kwargs['capture_frames'])
            paths=list((out/'reports').glob('*.json'));self.assertEqual(len(paths),1)
            from expectrail.orchestrator.playtest import load
            self.assertEqual(load(paths[0]),docs[0])
            self.assertEqual(json.loads((out/'summary.json').read_text())['reports'],[docs[0]['id']])

    def test_writer_refuses_uppercase_and_invalid_route_in_merged_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'report.json'
            bad = report(); bad['fault']['anchor']['object'] = 'Player'
            with self.assertRaises(ValueError):
                write_report(path, bad)
            self.assertFalse(path.exists())
            write_report(path, report())
            write_report(path, report())
            with self.assertRaises(ValueError):
                write_report(path, report(x=5))
            bad = report(); bad['route']['ticks'] = 1801
            with self.assertRaises(ValueError):
                write_report(Path(tmp) / 'too-long.json', bad)

    def test_complete_link_groups_do_not_chain_or_cross_build_or_observation(self):
        docs = [report('report-a', 0), report('report-b', 2), report('report-c', 4)]
        different = report('report-d'); different['target']['commit'] = 'b'*40
        symptom = report('report-e'); symptom['bug'] = 'My character falls.'
        result = groups(docs + [different, symptom])
        self.assertEqual(result, [['report-a', 'report-b'], ['report-c'], ['report-d'], ['report-e']])
        self.assertEqual(result, groups(list(reversed(docs + [different, symptom]))))
        self.assertEqual(sum(map(len, result)), 5)

    def test_group_tolerance_is_both_anchors_and_object_must_match(self):
        a, b = report('report-a'), report('report-b', 1)
        b['fault']['anchor']['tolerancePx'] = .5
        self.assertEqual(len(groups([a, b])), 2)
        b['fault']['anchor'].update(x=0, object='enemy')
        self.assertEqual(len(groups([a, b])), 2)

    def test_only_real_product_evidence_is_classified(self):
        reached = [{'run': i, 'coverage': {'reached': [True]}} for i in (1, 2, 3)]
        for reason, kind, checks, expected in [
            ('approved-check-reproduced', 'approved', ['ground'], 'approved'),
            ('anchor-desync', 'none', [], 'anchor-desync'),
            ('not-reproduced', 'none', [], 'not-reproduced'),
            ('playtest-reproduction-inconclusive: missing evidence or unstable failure', 'none', [], 'inconclusive'),
            ('unknown', 'none', [], 'unclassified')]:
            status = {'phase': 'completed', 'reproduction': {'kind': kind, 'checks': checks, 'reason': reason}}
            result = classify(status, reached)
            self.assertEqual(result['outcome'], expected)
            self.assertTrue(result['anchorReached3of3'])
            status['phase'] = 'failed'
            self.assertEqual(classify(status, reached)['outcome'], 'job-error')
        self.assertFalse(classify({}, reached[:2])['anchorReached3of3'])
        reached[0]['coverage']['reached'] = [None]
        self.assertFalse(classify({}, reached)['anchorReached3of3'])

    def test_completed_timeout_is_a_job_error_not_a_filter_rejection(self):
        status = {'phase': 'completed', 'decision': 'needs-review',
                  'diagnostics': [{'code': 'EXECUTION_TIMEOUT'}],
                  'reasons': ['EXECUTION_TIMEOUT: limit exceeded'],
                  'reproduction': {'kind': 'none', 'checks': [], 'reason': 'not-evaluated'}}
        result = classify(status, [])
        self.assertEqual(result['outcome'], 'job-error')
        self.assertEqual(result['jobReasons'], status['reasons'])

    def test_environment_does_not_inherit_provider_or_paid_settings(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            'EXPECTRAIL_VISION_URL': 'not-used', 'OPENAI_API_KEY': 'not-used',
            'EXPECTRAIL_MAX_COST': '100', 'DISPLAY': ':12'}):
            env = environment(Path(tmp), Path('/godot'))
            self.assertNotIn('EXPECTRAIL_VISION_URL', env)
            self.assertNotIn('OPENAI_API_KEY', env)
            self.assertNotIn('EXPECTRAIL_MAX_COST', env)
            self.assertEqual(env['DISPLAY'], ':12')

    def test_cli_is_real_subprocess_and_needs_review_exit_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / 'report.json'; write_report(path, report())
            def cli(argv, **kwargs):
                self.assertEqual(argv[1:4], ['-m', 'expectrail.cli', 'ingest'])
                self.assertNotIn('--propose', argv); self.assertNotIn('--repair', argv)
                store = Path(argv[argv.index('--jobs-root') + 1]) / 'jobs/job-one'
                store.mkdir(parents=True)
                (store / 'status.json').write_text(json.dumps({'id': 'job-one', 'phase': 'completed',
                    'decision': 'needs-review', 'reproduction': {'kind': 'none', 'checks': [], 'reason': 'not-reproduced'}}))
                return subprocess.CompletedProcess(argv, 2)
            with mock.patch('tools.playtester.command.subprocess.run', side_effect=cli) as invoke:
                result = ingest(path, root, root / 'intakes', Path('/godot'))
                self.assertEqual(result['exit'], 2)
                self.assertEqual(result['outcome'], 'not-reproduced')
                self.assertEqual(ingest(path, root, root / 'intakes', Path('/godot')), result)
                self.assertEqual(invoke.call_count, 1)
            changed = report(); changed['bug'] = 'Other words'
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, 'changed'):
                ingest(path, root, root / 'intakes', Path('/godot'))

    def test_compaction_retains_assets_results_and_hashes_removed_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'frames').mkdir()
            (root / 'frames/f000.png').write_bytes(b'frame')
            (root / 'replay.json').write_text(json.dumps({'format': 'expectrail.replay/v0',
                'capture': {'pattern': 'frames/f%08d.png'}}))
            (root / 'assets/frames').mkdir(parents=True)
            (root / 'assets/frames/fsource.png').write_bytes(b'asset-frame')
            (root / 'asset.png').write_bytes(b'asset')
            (root / 'trace.json').write_text('{}')
            (root / 'status.json').write_text('{}')
            compact(root)
            self.assertTrue((root / 'asset.png').exists())
            self.assertTrue((root / 'assets/frames/fsource.png').exists())
            self.assertTrue((root / 'status.json').exists())
            self.assertTrue((root / 'trace.json.gz').exists())
            self.assertFalse((root / 'frames/f000.png').exists())
            self.assertEqual(json.loads((root / 'removed-pngs.json').read_text())[0]['bytes'], 5)

    def test_modules_and_tests_load_without_numpy_and_pil(self):
        program = '''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.split('.')[0] in {'numpy', 'PIL'}: raise ImportError(fullname)
sys.meta_path.insert(0, Block())
import tools.playtester.command, tools.playtester.command_bench, tools.playtester.audit_command
import tests.test_playtester_command
'''
        done = subprocess.run([sys.executable, '-c', program], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
