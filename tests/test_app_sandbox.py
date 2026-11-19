"""App and command parity at the ordinary worker with Bubblewrap absent."""
from contextlib import redirect_stdout
import io
import os
import shutil
import unittest
from unittest import mock

from expectrail import cli
from expectrail.gate import record
from expectrail.orchestrator import engines, runner
from expectrail.orchestrator.store import JobStore
from harness import sandbox
from tests import test_app
from tests.test_ci_gate import FakeReplay


class SandboxParityTest(unittest.TestCase):
    def test_missing_bubblewrap_has_the_same_label_or_refusal(self):
        fixture = test_app.HTTPTest()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        # Use the public broken trace so the real gate rejects without a visual answer.
        (fixture.after / fixture.body['game'] / 'BUG').touch()
        replay = FakeReplay()

        def replay_without_bwrap(route, game, out, frames):
            tool, isolation = sandbox.choose(None, frames)
            self.assertIsNone(tool)
            return replay(route, game, out, frames) | {'isolation': isolation}

        fixture.engine = engines.GodotGate(replay=replay_without_bwrap)
        other = JobStore(fixture.root / 'cli-jobs')

        def work(store, job_id):
            with redirect_stdout(io.StringIO()):
                runner.work(store, job_id, engines={'godot': fixture.engine})

        actual_which = shutil.which
        def without_bwrap(name, *args, **kwargs):
            return None if name == 'bwrap' else actual_which(name, *args, **kwargs)

        with mock.patch.dict(os.environ, {'MODEL_API_KEY': '', 'EXPECTRAIL_SAM_USD_CAP': '',
                                           'EXPECTRAIL_SANDBOX': 'auto'}), \
             mock.patch.object(sandbox.sys, 'platform', 'linux'), \
             mock.patch.object(sandbox.shutil, 'which', side_effect=without_bwrap):
            for execution, decision, status in [('diagnostic', 'reject', 1), ('isolated', 'needs-review', 2)]:
                with self.subTest(execution=execution):
                    replay.calls.clear()
                    job = fixture.create(executionClass=execution)
                    shown = fixture.finished(job)
                    app_calls = len(replay.calls)
                    replay.calls.clear()
                    body = fixture.body
                    cmd = ['verify', '--jobs-root', str(other.root), '--execution-class', execution,
                           '--base', body['before'], '--head', body['after'], '--game', body['game'],
                           '--routes', body['routes'], '--specs', body['specs']]
                    with mock.patch.object(runner, 'spawn', side_effect=work), redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(cli.main(cmd), status)
                    cli_job, = [p.name for p in (other.root / 'jobs').iterdir()
                                if other.request(p.name)['executionClass'] == execution]
                    printed = other.status(cli_job)
                    self.assertEqual(fixture.store.request(job), other.request(cli_job))
                    self.assertEqual(shown['decision'], decision)
                    self.assertEqual(printed['decision'], decision)
                    self.assertEqual(shown['diagnostics'], printed['diagnostics'])
                    why = 'bubblewrap (bwrap) is not installed'
                    if execution == 'isolated':
                        self.assertEqual((app_calls, len(replay.calls)), (0, 0))
                        self.assertEqual(shown['screen'], 'could-not-be-carried-out')
                        self.assertIsNone(shown['isolation'])
                        self.assertIn(why, shown['diagnostics'][0]['detail'])
                        self.assertIn(shown['diagnostics'][0]['detail'], output.getvalue())
                    else:
                        self.assertGreater(app_calls, 0)
                        self.assertEqual(app_calls, len(replay.calls))
                        cli_finding = record.read_record(other.paths(cli_job).output / 'findings.json')
                        self.assertIn(why, shown['isolation'])
                        self.assertEqual(shown['isolation'], record.isolation_words(cli_finding['isolation']))
