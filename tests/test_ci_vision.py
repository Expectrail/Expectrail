"""CI's no-key expectations and the lost-worker fixture; no engine or model is started."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

from expectrail import doctor
from expectrail.orchestrator import runner
from expectrail.orchestrator.store import JobStore
from tests import test_replay_sandbox

ROOT = Path(__file__).resolve().parent.parent


class DoctorStepTest(unittest.TestCase):
    def setUp(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())
        self.script = next(step['run'] for step in workflow['jobs']['package']['steps']
                           if step.get('name', '').startswith('doctor from the installed copy'))
        self.doc = json.loads((ROOT / 'contracts/examples/doctor.json').read_text())
        for check in self.doc['checks']:
            if check['id'] not in ('vision-key', 'vision-cap'):
                check.update(status='ok', fix=None)
            if check['id'] == 'display':
                # The package job runs on Linux, where doctor makes the virtual display required. The
                # contract example (#391) shows it as a non-Linux machine does: skipped, not required.
                check.update(required=True)
        self.assertEqual(doctor.problems(self.doc), [])

    def run_step(self, doc, code=3):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'venv/bin').mkdir(parents=True)
            (root / 'venv/bin/python').symlink_to(sys.executable)
            command = root / 'venv/bin/expectrail'
            command.write_text('#!' + sys.executable + '\n' + '''import os, pathlib, sys
args = sys.argv[1:]
if args == ['doctor', '--json']:
    print(pathlib.Path('fixture.json').read_text())
    sys.exit(int(pathlib.Path('exit-code').read_text()))
if args == ['doctor']:
    if os.environ.get('EXPECTRAIL_GODOT', '').endswith('no-such-engine'):
        print('MISSING   Godot\\nfix: install the engine')
    else:
        print('2 required pieces missing (vision-key, vision-cap)')
    sys.exit(3)
if args == ['verify', '--head', '.']:
    sys.exit(5)
raise AssertionError(args)
''')
            command.chmod(0o755)
            (root / 'fixture.json').write_text(json.dumps(doc))
            (root / 'exit-code').write_text(str(code))
            env = {k: v for k, v in os.environ.items() if k not in ('MODEL_API_KEY', 'EXPECTRAIL_SAM_USD_CAP')}
            env.update(RUNNER_TEMP=tmp, PYTHONPATH=str(ROOT))
            return subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', self.script],
                                  cwd=root, env=env, text=True, capture_output=True, timeout=20)

    def test_exact_pair_and_exit_three_pass(self):
        done = self.run_step(self.doc)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_missing_neighbours_are_refused(self):
        for ids in (set(), {'vision-key'}, {'vision-cap'}, {'vision-key', 'vision-cap', 'display'}):
            with self.subTest(ids=ids):
                doc = copy.deepcopy(self.doc)
                for check in doc['checks']:
                    missing = check['id'] in ids
                    check.update(status='missing' if missing else 'ok', fix='Set up this piece.' if missing else None)
                doc['ok'] = not ids
                self.assertEqual(doctor.problems(doc), [])
                self.assertNotEqual(self.run_step(doc).returncode, 0)
        doc = copy.deepcopy(self.doc)
        display = next(c for c in doc['checks'] if c['id'] == 'display')
        display.update(status='skipped', fix='Install the display.')
        self.assertNotEqual(self.run_step(doc).returncode, 0)

    def test_wrong_exit_and_invalid_records_are_refused(self):
        for code in (0, 2, 5):
            with self.subTest(code=code):
                self.assertNotEqual(self.run_step(self.doc, code).returncode, 0)
        for broken in ({**self.doc, 'ok': True},
                       {**self.doc, 'checks': self.doc['checks'] + [self.doc['checks'][-1]]}):
            self.assertNotEqual(self.run_step(broken).returncode, 0)


class LostWorkerFixtureTest(unittest.TestCase):
    def test_worker_uses_real_replay_with_explicit_engine_only_and_same_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp), lease_seconds=2)
            with mock.patch.object(runner, 'spawn') as spawn:
                test_replay_sandbox.spawn_sandbox_worker(store, 'test-job')
            command = spawn.call_args.kwargs['command']
            self.assertEqual(command[:2], [sys.executable, '-c'])
            with mock.patch.object(runner, 'work') as work, mock.patch.object(sys, 'argv', ['-c', *command[3:]]):
                exec(compile(command[2], '<sandbox-worker>', 'exec'), {'__name__': '__main__'})
            supplied_store, job = work.call_args.args
            self.assertEqual((supplied_store.root, supplied_store.lease_seconds, job), (store.root, 2, 'test-job'))
            gate = work.call_args.kwargs['engines']['godot']
            self.assertEqual(gate._rule, 'engine-only')
            self.assertIsNone(gate._replay)  # no FakeReplay: the integration test must run Godot
            self.assertTrue(work.call_args.kwargs['own_group'])
