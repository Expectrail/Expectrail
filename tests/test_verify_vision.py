"""Orchestrator vision defaults, offline SAM answers, and replay environment separation (#379)."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail.gate import record
from expectrail.orchestrator import engines, request, runner, store, cli
from harness import run, sandbox
from tests.test_two_observers import Game, repo


class VerifyVisionTest(unittest.TestCase):
    def work(self, root, engine, look='clean'):
        jobs = store.JobStore(root / 'jobs')
        req = request.build(adapter='godot', head=repo(root / 'head', look), game='game/platformer',
                            routes=['routes/*.json'], specs='specs')
        status, _ = jobs.create(req)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = runner.work(jobs, status['id'], engines={'godot': engine})
        return jobs, status

    def test_missing_key_or_cap_sends_nothing_and_finishes_needs_review(self):
        for missing in ('MODEL_API_KEY', 'EXPECTRAIL_SAM_USD_CAP'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                env = {'MODEL_API_KEY': 'test-secret-379', 'EXPECTRAIL_SAM_USD_CAP': '0.50'}
                env[missing] = ''
                game = Game()
                with mock.patch.dict(os.environ, env), mock.patch('urllib.request.urlopen', side_effect=AssertionError('live call')) as sent:
                    jobs, status = self.work(Path(tmp), engines.GodotGate(replay=game.replay))
                self.assertEqual((status['phase'], status['decision']), ('completed', 'needs-review'))
                self.assertIn(missing, json.dumps(status['diagnostics']))
                self.assertIn('set ' + missing, json.dumps(status['diagnostics']))
                self.assertTrue(game.replays)
                doc = record.read_record(jobs.paths(status['id']).output / 'findings.json')
                self.assertEqual(doc['observers'], {'rule': 'both', 'visual': None})
                self.assertTrue(doc['checks'])
                self.assertTrue(all(c['observed']['after']['engine'] == 'pass' for c in doc['checks']))
                self.assertEqual({d['code'] for d in status['diagnostics']}, {'PROVIDER_FAILED'})
                sent.assert_not_called()
                self.assertNotIn('test-secret-379', json.dumps(status))

    def test_engine_failure_rejects_without_key_cap_or_both(self):
        for absent in (('MODEL_API_KEY',), ('EXPECTRAIL_SAM_USD_CAP',),
                       ('MODEL_API_KEY', 'EXPECTRAIL_SAM_USD_CAP')):
            with self.subTest(absent=absent), tempfile.TemporaryDirectory() as tmp:
                env = {'MODEL_API_KEY': 'test-secret-379', 'EXPECTRAIL_SAM_USD_CAP': '0.50'}
                env.update({key: '' for key in absent})
                game = Game()
                with mock.patch.dict(os.environ, env), mock.patch('urllib.request.urlopen') as sent:
                    jobs, status = self.work(Path(tmp), engines.GodotGate(replay=game.replay), 'BUG')
                self.assertEqual((status['phase'], status['decision']), ('completed', 'reject'))
                self.assertTrue(game.replays)
                doc = record.read_record(jobs.paths(status['id']).output / 'findings.json')
                self.assertEqual(doc['decision'], 'reject')
                self.assertEqual(doc['observers'], {'rule': 'both', 'visual': None})
                self.assertTrue(any(c['observed']['after']['engine'] == 'fail' for c in doc['checks']))
                self.assertTrue(all(c['observed']['after']['visual'] == 'not-asked' for c in doc['checks']))
                self.assertEqual(len(status['diagnostics']), len(absent))
                for key in absent:
                    self.assertIn(key, json.dumps(status['diagnostics']))
                self.assertEqual({d['code'] for d in status['diagnostics']}, {'PROVIDER_FAILED'})
                self.assertIn('vision did not run', ' '.join(status['reasons']))
                sent.assert_not_called()
                self.assertNotIn('test-secret-379', json.dumps(status))

    def test_invalid_cap_still_replays_and_never_accepts(self):
        for cap in ('', '-1', 'nan', 'inf', 'invalid'):
            with self.subTest(cap=cap), tempfile.TemporaryDirectory() as tmp:
                game = Game()
                with mock.patch.dict(os.environ, {'MODEL_API_KEY': 'test-secret-379', 'EXPECTRAIL_SAM_USD_CAP': cap}), \
                        mock.patch('urllib.request.urlopen') as sent:
                    _, status = self.work(Path(tmp), engines.GodotGate(replay=game.replay))
                self.assertEqual(status['decision'], 'needs-review')
                self.assertTrue(game.replays)
                self.assertIn('EXPECTRAIL_SAM_USD_CAP', json.dumps(status['diagnostics']))
                sent.assert_not_called()

    def test_default_rule_uses_frames_and_status_and_report_name_both_observers(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
                'MODEL_API_KEY': 'test-secret-379', 'EXPECTRAIL_SAM_USD_CAP': '0.50',
                # A cache of its own: answers other tests left in the shared cache would be served
                # without asking the model (it failed that way in the full suite).
                'XDG_CACHE_HOME': str(Path(tempfile.gettempdir()) / f'expectrail-379-cache-{os.getpid()}')}):
            shutil.rmtree(os.environ['XDG_CACHE_HOME'], ignore_errors=True)
            self.addCleanup(shutil.rmtree, os.environ['XDG_CACHE_HOME'], True)
            game = Game()
            supplied_envs = []

            original_run = subprocess.run

            def replay_process(cmd, **kwargs):
                trace_arg = next((arg[8:] for arg in cmd if arg.startswith('--trace=')), None)
                if trace_arg is None:
                    return original_run(cmd, **kwargs)
                # The stand-in game records the environment supplied by the real harness.
                supplied_envs.append(dict(kwargs['env']))
                self.assertNotIn('MODEL_API_KEY', kwargs['env'])
                route = Path(next(arg[8:] for arg in cmd if arg.startswith('--route=')))
                project = Path(cmd[cmd.index('--path') + 1])
                out = Path(trace_arg).parent
                played = game.replay(route, project, out, True)
                Path(trace_arg).write_text(json.dumps(played['trace']))
                return subprocess.CompletedProcess(cmd, 0, '', '')

            # Real gate, adapter and harness; only engine execution and the model are stand-ins.
            with mock.patch('expectrail.observers.FramesObserver._model', return_value=game.observer()._client), \
                    mock.patch('agents.sam_observations._usage', {'requests': 0, 'images': 0, 'videoFrames': 0, 'reservedUsd': 0.0}), \
                    mock.patch.object(engines.GodotGate, '_tools', return_value=[]), \
                    mock.patch.object(run, 'find_godot', return_value=Path('/fake/godot')), \
                    mock.patch.object(run, 'ensure_import_cache', return_value=None), \
                    mock.patch.object(run, 'godot_import'), \
                    mock.patch.object(run.subprocess, 'run', side_effect=replay_process), \
                    mock.patch.dict(os.environ, {'EXPECTRAIL_SANDBOX': 'off'}):
                jobs, status = self.work(Path(tmp), engines.Engines()['godot'])
            self.assertEqual(status['decision'], 'accept')
            doc = record.read_record(jobs.paths(status['id']).output / 'findings.json')
            self.assertEqual(status['observers'], doc['observers'])
            self.assertEqual(status['observers']['rule'], 'both')
            self.assertTrue(game.asked)
            self.assertTrue(supplied_envs)
            self.assertIn('two observers on every check', cli.describe(status))
            reported = io.StringIO()
            with contextlib.redirect_stdout(reported):
                code = cli.main(['--jobs-root', str(jobs.root), 'report', status['id']])
            self.assertEqual(code, 0)
            self.assertIn('two observers on every check', reported.getvalue())
            for path in jobs.paths(status['id']).root.rglob('*'):
                if path.is_file():
                    self.assertNotIn(b'test-secret-379', path.read_bytes(), str(path))

    def test_real_harness_and_sandbox_allowlists_drop_the_model_key(self):
        source = {'MODEL_API_KEY': 'test-secret-379', 'EXPECTRAIL_SAM_USD_CAP': '0.50',
                  'PATH': '/usr/bin:/bin', 'LIBGL_ALWAYS_SOFTWARE': '1'}
        self.assertNotIn('MODEL_API_KEY', run.game_env(source))
        with tempfile.TemporaryDirectory() as tmp:
            cmd = sandbox.command(sandbox.Tool('/usr/bin/bwrap', 'test'), ['true'],
                                  game=Path(tmp), out=Path(tmp), env=source)
        self.assertIn('--clearenv', cmd)
        self.assertNotIn('MODEL_API_KEY', cmd)
        self.assertNotIn('test-secret-379', cmd)
