"""The timed CI walkthrough stays keyless; recorded missing prerequisites have fixes.

Only the named CI job and public docs are read. Shell execution uses tiny offline
stand-ins; doctor uses its existing stand-in-machine fixture, never a real model.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

from expectrail import doctor
from tests import test_doctor as fixtures

ROOT = Path(__file__).resolve().parent.parent


class QuickstartJobTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load((ROOT/'.github/workflows/ci.yml').read_text())
        cls.job = cls.workflow['jobs']['quickstart-timing']
        cls.steps = cls.job['steps']

    def test_job_is_independent_read_only_and_has_no_secrets_or_protected_environment(self):
        self.assertEqual(self.job['runs-on'], 'ubuntu-24.04')
        self.assertEqual(self.workflow['permissions'], {'contents':'read'})
        self.assertEqual(self.job['permissions'], {'contents':'read'})
        self.assertNotIn('environment', self.job)
        self.assertNotIn('needs', self.job)
        self.assertNotIn('continue-on-error', self.job)
        text = yaml.safe_dump(self.job) + yaml.safe_dump(self.workflow.get('env', {}))
        self.assertNotIn('secrets.', text)
        self.assertNotIn('write', text)
        for key in ('MODEL_API_KEY','META_API_KEY','EXPECTRAIL_SAM_USD_CAP'):
            self.assertNotIn(key, text)
        for step in self.steps:
            self.assertNotIn('continue-on-error', step)
        events = self.workflow.get('on', self.workflow.get(True))
        self.assertIn('pull_request', events)
        self.assertNotIn('pull_request_target', events)

    def test_shared_actions_prepare_the_display_and_verified_engine_before_timing(self):
        uses = [s.get('uses', '') for s in self.steps]
        checkout = next(s for s in self.steps if s.get('uses', '').startswith('actions/checkout@'))
        self.assertIs(checkout['with']['persist-credentials'], False)
        apt = next(s for s in self.steps if s.get('uses') == './.github/actions/apt-install')
        godot = next(s for s in self.steps if s.get('uses') == './.github/actions/get-godot')
        self.assertEqual(apt['with']['restore-only'], 'true')
        self.assertEqual(godot['with']['restore-only'], 'true')
        packages = set(apt['with']['packages'].split())
        self.assertTrue({'xvfb','xauth','libgl1-mesa-dri','libglx-mesa0','patch','curl','unzip'} <= packages)
        timing = next(s for s in self.steps if 'tools.quickstart_timer' in s.get('run', ''))
        self.assertLess(self.steps.index(checkout), self.steps.index(apt))
        self.assertLess(self.steps.index(apt), self.steps.index(godot))
        self.assertLess(self.steps.index(godot), self.steps.index(timing))
        self.assertIn('xvfb-run -a python3 -m tools.quickstart_timer --out runs/quickstart-timing', timing['run'])
        self.assertIn('EXPECTRAIL_GODOT', timing['run'])
        self.assertIn('find_godot()', timing['run'])
        for use in uses:
            if use and not use.startswith('./'):
                self.assertRegex(use, r'@[0-9a-f]{40}$')

    def test_upload_keeps_the_timing_record_and_diagnostics_even_on_failure(self):
        upload, = [s for s in self.steps if s.get('uses', '').startswith('actions/upload-artifact@')]
        self.assertEqual(upload['if'], 'always()')
        self.assertEqual(upload['with']['name'], 'quickstart-timing')
        self.assertIn('runs/quickstart-timing/quickstart-timing.json', upload['with']['path'].splitlines())
        self.assertIn('runs/quickstart-timing/doctor.json', upload['with']['path'].splitlines())
        self.assertIn('runs/quickstart-timing/commands/', upload['with']['path'].splitlines())
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        self.assertLess(next(i for i,s in enumerate(self.steps) if 'tools.quickstart_timer' in s.get('run','')),
                        self.steps.index(upload))

    def test_the_actual_job_shell_propagates_an_incomplete_timer_exit(self):
        # Execute the workflow text as GitHub's bash step does. These executables
        # only record argv and return a chosen status; no pip, Godot or network.
        script = next(s['run'] for s in self.steps if 'tools.quickstart_timer' in s.get('run',''))
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            def program(name, body):
                p = work/name
                p.write_text(f'#!{sys.executable}\n' + body)
                p.chmod(p.stat().st_mode | stat.S_IXUSR)
            program('python3', '''import json, os, sys
if sys.argv[1] == '-c':
    if int(os.environ['RESOLVE_EXIT']):
        sys.exit(int(os.environ['RESOLVE_EXIT']))
    print('/prepared/godot')
else:
    with open(os.environ['CALLS'], 'w') as f:
        json.dump({'argv':sys.argv[1:], 'godot':os.environ.get('EXPECTRAIL_GODOT')}, f)
    sys.exit(int(os.environ['TIMER_EXIT']))
''')
            program('xvfb-run', '''import os, sys
assert sys.argv[1] == '-a'
os.execvp(sys.argv[2], sys.argv[2:])
''')
            for resolve, code, expected in ((0, 0, 0), (0, 2, 2), (7, 0, 7)):
                (work/'calls.json').unlink(missing_ok=True)
                env = {'PATH':str(work)+os.pathsep+os.defpath, 'CALLS':str(work/'calls.json'),
                       'TIMER_EXIT':str(code), 'RESOLVE_EXIT':str(resolve)}
                result = subprocess.run(['bash','--noprofile','--norc','-eo','pipefail','-c',script],
                                        cwd=work, env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, expected, result.stderr)
                if resolve:
                    self.assertFalse((work/'calls.json').exists())
                    continue
                called = json.loads((work/'calls.json').read_text())
                self.assertEqual(called['argv'], ['-m','tools.quickstart_timer','--out','runs/quickstart-timing'])
                self.assertEqual(called['godot'], '/prepared/godot')

    def test_both_entry_documents_name_the_recorded_prerequisites(self):
        for name in ('README.md','docs/quickstart.html'):
            text = (ROOT/name).read_text()
            for word in ('xvfb-run','libgl1-mesa-dri','libglx-mesa0','1 GiB','1024 MB',
                         'Bubblewrap','MODEL_API_KEY','EXPECTRAIL_SAM_USD_CAP'):
                self.assertIn(word, text, (name, word))


class RecordedPrerequisitesTest(fixtures.Machine):
    WHY = "xvfb-run is not installed, and the sandbox cannot use the host's display"

    def test_doctor_names_all_recorded_missing_prerequisites_and_their_fixes(self):
        self.programs.remove('xvfb-run')
        self.free = 533 * 1024**2
        with mock.patch.dict(os.environ, {'MODEL_API_KEY':'', 'EXPECTRAIL_SAM_USD_CAP':''}), \
                mock.patch('harness.sandbox.probe', return_value=(None, self.WHY)):
            code, text, err = self.run_doctor()
            json_code, output, _ = self.run_doctor('--json')
        self.assertEqual((code, json_code, err), (3, 3, ''))
        doc = json.loads(output)
        self.assertEqual(doctor.problems(doc), [])
        by_id = {c['id']:c for c in doc['checks']}
        actual = {k:c['status'] for k,c in by_id.items() if c['status'] != 'ok'}
        self.assertEqual(actual, {'display':'missing','opengl':'skipped','disk':'missing',
                                  'sandbox':'missing','vision-key':'missing','vision-cap':'missing'})
        self.assertFalse(by_id['sandbox']['required'])
        for name in actual:
            self.assertTrue(by_id[name]['fix'], name)
            self.assertIn(by_id[name]['fix'], text)
        self.assertIn('sudo apt-get install xvfb', by_id['display']['fix'])
        self.assertIn('not tried', by_id['opengl']['found'])
        self.assertIn('doctor', by_id['opengl']['fix'])
        self.assertIn('533 MB free', by_id['disk']['found'])
        self.assertIn('1024 MB', by_id['disk']['fix'])
        self.assertIn('EXPECTRAIL_TOOLS and TMPDIR', by_id['disk']['fix'])
        self.assertIn('sudo apt-get install xvfb', by_id['sandbox']['fix'])
        self.assertNotIn('apt-get install bubblewrap', by_id['sandbox']['fix'])
        self.assertIn('MODEL_API_KEY', by_id['vision-key']['fix'])
        self.assertIn('EXPECTRAIL_SAM_USD_CAP', by_id['vision-cap']['fix'])
        self.assertNotIn(fixtures.SECRET, text + output)

    def test_disk_checks_both_locations_without_lowering_the_existing_threshold(self):
        engine, temporary = self.tmp/'tools', self.tmp/'scratch'
        engine.mkdir(); temporary.mkdir()
        for low in (engine, temporary, None):
            def usage(path):
                free = doctor.MIN_FREE_BYTES - 1 if path == low else doctor.MIN_FREE_BYTES
                return fixtures.Usage(10*doctor.MIN_FREE_BYTES, 0, free)
            with self.subTest(low=low), mock.patch('harness.run.tools_dir', return_value=engine), \
                    mock.patch.object(doctor.tempfile, 'gettempdir', return_value=str(temporary)), \
                    mock.patch.object(doctor.shutil, 'disk_usage', side_effect=usage):
                check = doctor.disk()
            self.assertEqual(check.status, 'ok' if low is None else 'missing')
            if low is not None:
                self.assertIn(str(low), check.found)
                self.assertIn('1024 MB', check.fix)
        self.assertEqual(doctor.MIN_FREE_BYTES, 1024**3)

    def test_the_display_fix_preserves_optional_and_required_sandbox_decisions(self):
        with mock.patch('harness.sandbox.probe', return_value=(None, self.WHY)):
            for required in (False, True):
                check = doctor.sandbox(required)
                self.assertEqual((check.status, check.required), ('missing', required))
                self.assertIn('sudo apt-get install xvfb', check.fix)
                self.assertIn('require-sandbox', check.fix)
        with mock.patch('harness.sandbox.probe', return_value=(None, 'bubblewrap (bwrap) is not installed')):
            self.assertIn('sudo apt-get install bubblewrap', doctor.sandbox(False).fix)

    def test_a_failed_drawing_probe_names_the_mesa_packages(self):
        self.set_engine(draws='No renderer available', code=1)
        check = self.by_id()['opengl']
        self.assertEqual((check.status, check.required), ('missing', True))
        self.assertIn('libgl1-mesa-dri', check.fix)
        self.assertIn('libglx-mesa0', check.fix)


if __name__ == '__main__':
    unittest.main()
