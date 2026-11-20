"""Small close-out gaps; fixtures only, no model, renderer or game process."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents import fixer
from expectrail import app, renderer
from tests import test_repair_command as repair_tests
from tests.test_app_projects import configured_project


class RepairAgentCommandTest(unittest.TestCase):
    # Reuse the unchanged rejected-job fixture and ordinary worker, not a new loop.
    setUp = repair_tests.RepairCommandTest.setUp
    invoke = repair_tests.RepairCommandTest.invoke
    record = repair_tests.RepairCommandTest.record

    def test_explicit_llm_patch_reaches_existing_fixer_and_fresh_gate(self):
        with mock.patch.object(fixer, 'run_fixer', wraps=fixer.run_fixer) as calls:
            code, output = self.invoke('--agent', 'llm-patch')
        self.assertEqual(code, 0, output)
        self.assertEqual(calls.call_count, 1)
        self.assertEqual(calls.call_args.kwargs['agent'], 'llm-patch')
        self.assertTrue(calls.call_args.kwargs['provider_only'])
        self.assertEqual(calls.call_args.kwargs['candidate_patch'], repair_tests.FIX)
        _, record = self.record()
        self.assertEqual(record['fixer']['source'], 'fixture')
        self.assertEqual(record['result']['decision'], 'accept')
        self.assertNotEqual(record['result']['job'], self.parent)
        self.assertEqual(self.jobs.status(self.parent)['decision'], 'reject')
        self.assertEqual((self.bug / self.player).read_bytes(), self.original)

    def test_unknown_agent_never_falls_back_or_constructs_a_fixer(self):
        with mock.patch.object(fixer, 'run_fixer') as calls:
            code, output = self.invoke('--agent', 'unpriced-agent')
        self.assertEqual(code, 5, output)
        self.assertIn('unpriced-agent', output)
        calls.assert_not_called()
        self.assertFalse(list(self.jobs.paths(self.parent).root.glob('repair-*')))


class AppSetupInspectionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = configured_project(Path(tmp.name) / 'game')

    def inspect(self, probe):
        with mock.patch.object(renderer, 'machine', return_value=probe), \
             mock.patch.object(app.App, 'create', side_effect=AssertionError('job started')), \
             mock.patch('agents.sam_observations.MetaSamClient', side_effect=AssertionError('model started')):
            return app.inspect_project({'folder': str(self.project), 'projectConfig': True})

    def test_live_vision_inspection_names_missing_tools_before_verification(self):
        for reason, fix in (
            ('godot: Godot 4.7.2 is not installed', 'Install pinned Godot 4.7.2.'),
            ('display: xvfb-run is missing', 'Install xvfb.'),
            ('opengl: drawing probe failed', 'Restore software OpenGL.'),
        ):
            with self.subTest(reason=reason):
                result = self.inspect({'environment': None, 'reason': reason, 'fix': fix})
                report = result['rendering']
                self.assertTrue(report['warning'], report)
                self.assertIsNone(report['recording'])
                self.assertIn(reason, report['message'])
                self.assertIn(fix, report['fix'])
                self.assertEqual((result['routes'], result['checks']), (1, 1))

    def test_available_live_renderer_names_version_without_a_false_warning(self):
        environment = {'name': 'godot', 'version': '4.7.2.test',
                       'renderer': 'opengl3', 'device': 'stand-in software renderer'}
        report = self.inspect({'environment': environment, 'reason': None, 'fix': None})['rendering']
        self.assertFalse(report['warning'])
        self.assertIsNone(report['fix'])
        self.assertIn('4.7.2.test', report['message'])
        self.assertIn('No recorded vision selected', report['message'])
