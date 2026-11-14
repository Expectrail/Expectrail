"""Offline timing/contract tests: real tiny shells, no install, engine, or model."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import jsonschema

from tools import quickstart_timer as timer


class TimerTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.work = self.root/'work'
        self.work.mkdir()
        self.out = self.root/'out'
        self.out.mkdir()
        self.env = timer.clean_environment(self.root, os.environ)
        guard = mock.patch('urllib.request.urlopen', side_effect=AssertionError('no network in timer tests'))
        guard.start()
        self.addCleanup(guard.stop)

    def run_steps(self, steps, **kwargs):
        return timer.run_steps(steps, self.work, self.env, self.out, **kwargs)

    def test_unavailable_shell_is_not_run_never_completed_or_passed(self):
        steps = [{'name':'install', 'command':'do not execute', 'exit':0},
                 {'name':'sample', 'command':'do not execute either', 'exit':3}]
        clock = mock.Mock(side_effect=AssertionError('an unrun step has no timing'))
        unavailable = mock.Mock(side_effect=FileNotFoundError('Bash is not installed'))
        rows = self.run_steps(steps, shell_factory=unavailable, clock=clock)
        self.assertEqual([r['status'] for r in rows], ['not run', 'not run'])
        for row in rows:
            self.assertIsNone(row['exit_code'])
            self.assertIsNone(row['seconds'])
            self.assertIn('Bash is not installed', row['reason'])
        clock.assert_not_called()

    def test_failure_records_actual_exit_and_first_error_lines_and_elapsed_seconds(self):
        command = 'printf "first error\\nsecond error\\n" >&2; (exit 7)'
        rows = self.run_steps([{'name':'install','command':command,'exit':0}],
                              clock=mock.Mock(side_effect=[10., 12.25]))
        row = rows[0]
        self.assertEqual((row['status'], row['exit_code'], row['seconds']), ('failed', 7, 2.25))
        self.assertEqual(row['command'], command)
        self.assertEqual(row['error_lines'], ['first error','second error'])
        doc = json.loads((timer.ROOT/'contracts/examples/quickstart-timing.json').read_text())
        doc['steps'] = rows
        timer.write_timing(doc, self.out/'quickstart-timing.json')
        jsonschema.Draft202012Validator(json.loads(timer.SCHEMA.read_text())).validate(timer.read_timing(self.out/'quickstart-timing.json'))
        self.assertIn('documented exit is 0', row['reason'])
        self.assertEqual((self.out/row['stderr']).read_text(), 'first error\nsecond error\n')

    def test_exact_blocks_keep_shell_state_and_expected_nonzero_is_not_a_verdict(self):
        steps = [{'name':'one','command':'PROJECT="a path with spaces"\n(exit 3)','exit':3},
                 {'name':'two','command':'printf "%s" "$PROJECT"','exit':0}]
        rows = self.run_steps(steps)
        self.assertEqual([r['status'] for r in rows], ['completed', 'completed'])
        self.assertEqual([r['exit_code'] for r in rows], [3, 0])
        self.assertEqual((self.out/rows[1]['stdout']).read_text(), 'a path with spaces')
        self.assertEqual([r['command'] for r in rows], [s['command'] for s in steps])

    def test_missing_godot_blocks_replay_but_doctor_was_actually_executed(self):
        doc = json.loads((timer.ROOT/'contracts/examples/doctor.json').read_text())
        # Keep the real valid doctor's missing-engine findings, without invoking Godot.
        self.assertTrue(any(c['id']=='godot' and c['status']=='missing' for c in doc['checks']))
        (self.work/'doctor.json').write_text(json.dumps(doc))
        rows = self.run_steps([{'name':'install','command':'true','exit':0},
                              {'name':'doctor','command':'(exit 3)','exit':3},
                              {'name':'sample','command':'touch replay-started','exit':3}])
        self.assertEqual(rows[1]['status'], 'completed')
        self.assertEqual(rows[1]['exit_code'], 3)
        self.assertEqual(rows[2]['status'], 'not run')
        self.assertIsNone(rows[2]['seconds'])
        self.assertIn('godot', rows[2]['reason'])
        self.assertFalse((self.work/'replay-started').exists())

    def test_failed_install_blocks_dependent_command(self):
        rows = self.run_steps([{'name':'install','command':'(exit 9)','exit':0},
                              {'name':'doctor','command':'touch should-not-exist','exit':3}])
        self.assertEqual(rows[0]['exit_code'], 9)
        self.assertEqual(rows[1]['status'], 'not run')
        self.assertIn('install', rows[1]['reason'])
        self.assertFalse((self.work/'should-not-exist').exists())

    def test_timeout_is_failed_attempt_not_an_unrun_or_completed_step(self):
        # A fake select timeout avoids real sleeping; it stops a real idle shell.
        with mock.patch.object(timer.select, 'select', return_value=([], [], [])):
            row = self.run_steps([{'name':'one','command':'read line','exit':0}], timeout=.1)[0]
        self.assertEqual(row['status'], 'failed')
        self.assertIsInstance(row['exit_code'], int)
        self.assertGreaterEqual(row['seconds'], 0)
        self.assertIn('exceeded', row['reason'])

    def test_measure_uses_a_fresh_copy_removes_it_and_keeps_a_valid_record(self):
        copies = []
        def copy_inputs(source, destination):
            copies.append(destination)
            destination.mkdir()
        out = self.root/'measurement'
        steps = [{'name':'fixture','command':'printf "%s" "${MODEL_API_KEY-unset}"','exit':0}]
        with mock.patch.object(timer, 'documented_steps', return_value=steps), \
                mock.patch.object(timer.quickstart, 'copy_checkout', side_effect=copy_inputs), \
                mock.patch.object(timer.quickstart, 'validate_results') as evidence, \
                mock.patch.dict(os.environ, {'MODEL_API_KEY':'must-not-appear'}):
            doc = timer.measure(out)
        self.assertEqual(len(copies), 1)
        self.assertNotEqual(copies[0], timer.ROOT)
        self.assertFalse(copies[0].exists())
        self.assertEqual(doc['steps'][0]['status'], 'completed')
        self.assertEqual((out/doc['steps'][0]['stdout']).read_text(), 'unset')
        self.assertNotIn('must-not-appear', (out/'quickstart-timing.json').read_text())
        self.assertEqual(timer.read_timing(out/'quickstart-timing.json'), doc)
        evidence.assert_called_once_with(copies[0])

    def test_a_command_ending_the_shell_keeps_its_exit_and_blocks_later_steps(self):
        rows = self.run_steps([{'name':'one','command':'echo goodbye >&2; exit 7','exit':0},
                              {'name':'two','command':'touch never-ran','exit':0}])
        self.assertEqual((rows[0]['status'], rows[0]['exit_code']), ('failed', 7))
        self.assertEqual(rows[0]['error_lines'], ['goodbye'])
        self.assertEqual(rows[1]['status'], 'not run')
        self.assertFalse((self.work/'never-ran').exists())

    def test_network_routing_is_preserved_without_proxy_credentials(self):
        target = self.root/'network'
        target.mkdir()
        env = timer.clean_environment(target, {
            'HTTPS_PROXY':'http://proxy.invalid:8080', 'SSL_CERT_FILE':'/public-ca.pem',
            'HTTP_PROXY':'http://username:secret@proxy.invalid',
            'ALL_PROXY':'http://proxy.invalid?token=secret'})
        self.assertEqual(env['HTTPS_PROXY'], 'http://proxy.invalid:8080')
        self.assertEqual(env['SSL_CERT_FILE'], '/public-ca.pem')
        self.assertNotIn('HTTP_PROXY', env)
        self.assertNotIn('ALL_PROXY', env)
        self.assertNotIn('secret', json.dumps(env))

    def test_environment_cannot_inherit_keys_startup_hooks_or_provider_settings(self):
        inherited = {'PATH':os.defpath, 'MODEL_API_KEY':'do-not-pass', 'META_API_KEY':'do-not-pass',
                     'EXPECTRAIL_SAM_USD_CAP':'100', 'ANTHROPIC_API_KEY':'do-not-pass',
                     'EXPECTRAIL_VLM_COMMAND':'paid command', 'BASH_ENV':'startup', 'PYTHONPATH':'injection',
                     'PIP_INDEX_URL':'https://secret@example.invalid', 'HOME':'/real-home'}
        target = self.root/'clean'
        target.mkdir()
        env = timer.clean_environment(target, inherited)
        for name in inherited.keys()-{'PATH','HOME'}:
            self.assertNotIn(name, env)
        self.assertNotIn('do-not-pass', json.dumps(env))
        self.assertEqual(env['HOME'], str(target/'home'))
        self.assertEqual(env['PIP_CONFIG_FILE'], os.devnull)


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.example = json.loads((timer.ROOT/'contracts/examples/quickstart-timing.json').read_text())
        self.schema = json.loads(timer.SCHEMA.read_text())

    def test_schema_example_writer_and_reader_agree(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'quickstart-timing.json'
            timer.write_timing(self.example, out)
            doc = timer.read_timing(out)
        jsonschema.Draft202012Validator(self.schema).validate(doc)
        self.assertEqual(doc, self.example)
        self.assertIn('not run', timer.summary(doc))

    def test_reader_refuses_fabricated_completion_duplicate_steps_and_nonfinite_times(self):
        for change in ('completion','duplicates','nonfinite','evidence'):
            doc = copy.deepcopy(self.example)
            row = doc['steps'][0]
            if change == 'completion':
                row.update(status='completed', exit_code=0, seconds=1, stdout='out', stderr='err')
            elif change == 'duplicates':
                doc['steps'].append(copy.deepcopy(row))
            elif change == 'nonfinite':
                row.update(status='failed', seconds=float('nan'), stdout='out', stderr='err')
            else:
                doc['evidence_check']['status'] = 'completed'
            with self.subTest(change=change), self.assertRaises(ValueError):
                timer.validate_timing(doc)

    def test_not_run_cannot_have_an_exit_or_elapsed_seconds(self):
        for key, value in [('exit_code',0),('seconds',0),('reason',None)]:
            doc = copy.deepcopy(self.example)
            doc['steps'][0][key] = value
            with self.subTest(key=key), self.assertRaises(jsonschema.ValidationError):
                jsonschema.Draft202012Validator(self.schema).validate(doc)

    def test_commands_are_the_published_blocks_and_readme_install(self):
        steps = timer.documented_steps()
        self.assertEqual(steps, timer.quickstart.commands())
        self.assertEqual([s['name'] for s in steps], ['install','doctor','sample','project','verify','report'])
        self.assertIn('python3 -m pip install .', steps[0]['command'])


if __name__ == '__main__':
    unittest.main()
