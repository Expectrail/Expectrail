"""Darwin's ps cleanup path, exercised on Linux without calling native macOS or live models."""
from __future__ import annotations

import contextlib
import errno
import io
import os
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from expectrail.orchestrator import cli, request, store as st
from tests.test_ci_gate import make_repo

JOB = 'a' * 32
OTHER = 'b' * 32
MARKER = f'{st.JOB_ENV}={JOB}'


class PsMachine:
    """A same-user ps process table. Commands and expanded environments are separate reads."""
    def __init__(self):
        self.uid = os.getuid()
        self.caller = os.getpid()
        self.rows = {self.caller: (1, self.uid, 'S', 'caller', [])}
        self.calls = []

    def add(self, pid, env=(), *, parent=1, uid=None, state='S', command='game'):
        self.rows[pid] = (parent, self.uid if uid is None else uid, state, command, list(env))

    def run(self, cmd, **kw):
        self.calls.append((cmd, kw))
        assert cmd[0] == 'ps'
        assert cmd[cmd.index('-U') + 1] == str(self.uid)
        assert '-ww' in cmd
        assert st.JOB_ENV not in kw['env']
        # Include another user's row to hold the parser's uid guard too.
        rows = []
        for pid, (parent, uid, state, command, env) in self.rows.items():
            full = command + (' ' + ' '.join(env) if '-E' in cmd and env else '')
            rows.append(f' {pid} {parent} {uid} {state} {full}')
        return subprocess.CompletedProcess(cmd, 0, '\n'.join(rows) + '\n', '')

    def kill(self, pid, sig):
        if pid not in self.rows:
            raise ProcessLookupError
        if sig:
            self.rows.pop(pid)

    @contextlib.contextmanager
    def installed(self):
        exists = Path.exists
        def has_path(path):
            return False if str(path) == '/proc/self/environ' else exists(path)
        with mock.patch.object(Path, 'exists', has_path), mock.patch.object(st.subprocess, 'run', side_effect=self.run):
            yield self


class PsDiscoveryTest(unittest.TestCase):
    def test_only_exact_same_user_environment_markers_are_found_and_argv_is_not_an_environment(self):
        machine = PsMachine()
        machine.add(1101, [MARKER])
        machine.add(1102, [f'{st.JOB_ENV}={OTHER}'])
        machine.add(1103, [MARKER + '0'])
        machine.add(1104, [f'NOTE={MARKER}'])
        machine.add(1105, [], command=f'game {MARKER}')
        machine.add(1106, [MARKER], uid=machine.uid + 1)
        machine.add(1107, [MARKER], state='Z')
        with machine.installed():
            self.assertEqual(st.processes_of(JOB), [1101])
        self.assertTrue(machine.calls)

    def test_callers_and_their_ancestors_are_excluded_and_reported(self):
        machine = PsMachine()
        machine.add(machine.caller, [MARKER], parent=8001, command='caller')
        machine.add(8001, [MARKER], parent=1, command='shell')
        machine.add(1101, [MARKER])
        with machine.installed():
            self.assertEqual(st.processes_of(JOB), [1101])
            self.assertEqual(st._stopped_note(JOB, (0, 0)), "left 2 running: they are the caller's own")

    def test_a_process_is_rechecked_and_never_signalled_if_its_environment_no_longer_names_the_job(self):
        machine = PsMachine()
        machine.add(1101, [MARKER])
        with machine.installed(), mock.patch.object(st.os, 'kill') as kill:
            self.assertEqual(st.processes_of(JOB), [1101])
            machine.add(1101, [f'{st.JOB_ENV}={OTHER}'])
            self.assertIsNone(st._signal(1101, MARKER.encode(), signal.SIGTERM))
        kill.assert_not_called()

    def test_environment_removal_does_not_count_a_live_process_as_stopped(self):
        machine = PsMachine()
        machine.add(1101, [MARKER])
        original_run = machine.run
        reads = 0
        def changes_marker(cmd, **kw):
            nonlocal reads
            if '-E' in cmd:
                reads += 1
                if reads == 3:   # discovery twice, then immediately before the first signal
                    machine.add(1101, [])
            return original_run(cmd, **kw)
        with machine.installed(), mock.patch.object(st.subprocess, 'run', side_effect=changes_marker), \
                mock.patch.object(st.os, 'kill') as kill:
            self.assertEqual(st.stop_job(JOB, grace_seconds=0), (1, 0))
            self.assertIn('the rest are still running', st._stopped_note(JOB, (1, 0)))
        kill.assert_not_called()

    def test_a_process_that_leaves_the_same_user_ps_view_is_not_assumed_stopped(self):
        machine = PsMachine()
        machine.add(1101, [MARKER])
        original_run = machine.run
        reads = 0
        def changes_owner(cmd, **kw):
            nonlocal reads
            if '-E' in cmd:
                reads += 1
                if reads == 3:
                    machine.add(1101, [], uid=machine.uid + 1)
            return original_run(cmd, **kw)
        with machine.installed(), mock.patch.object(st.subprocess, 'run', side_effect=changes_owner), \
                mock.patch.object(st.os, 'kill', side_effect=PermissionError) as sent:
            self.assertEqual(st.stop_job(JOB, grace_seconds=0), (1, 0))
        self.assertEqual(sent.call_args_list, [mock.call(1101, 0)])

    def test_term_then_kill_and_a_later_child_are_counted_by_confirmed_exit(self):
        machine = PsMachine()
        machine.add(1101, [MARKER])
        sent = []
        def signal_process(pid, sig):
            if sig == 0:
                if pid not in machine.rows:
                    raise ProcessLookupError
                return
            sent.append((pid, sig))
            if sig == signal.SIGTERM:
                machine.add(1102, [MARKER], parent=1101)
            else:
                machine.rows.pop(pid)
        with machine.installed(), mock.patch.object(st.os, 'kill', side_effect=signal_process):
            ways = set()
            self.assertEqual(st.stop_job(JOB, grace_seconds=0, ways=ways), (2, 2))
            self.assertEqual(ways, {'number'})
        self.assertEqual(sent, [(1101, signal.SIGTERM), (1101, signal.SIGKILL), (1102, signal.SIGKILL)])

    def test_ps_errors_never_include_output_or_environment_values(self):
        for result in (subprocess.CompletedProcess([], 1, 'SENSITIVE', 'SENSITIVE'),
                       subprocess.CompletedProcess([], 0, 'SENSITIVE', ''),
                       FileNotFoundError('SENSITIVE'), subprocess.TimeoutExpired('ps', 5, output='SENSITIVE')):
            with self.subTest(result=type(result).__name__), PsMachine().installed():
                kwargs = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
                with mock.patch.object(st.subprocess, 'run', **kwargs):
                    with self.assertRaises(st.StoreError) as error:
                        st.processes_of(JOB)
                self.assertNotIn('SENSITIVE', str(error.exception))

    def test_inspection_failure_mid_stop_never_reports_success(self):
        machine = PsMachine()
        machine.add(1101, [MARKER])
        with machine.installed(), mock.patch.object(st, 'processes_of', side_effect=[[1101], None]):
            with self.assertRaisesRegex(st.StoreError, 'could not confirm'):
                st.stop_job(JOB)


class CancelReportingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='cancel-no-proc-')
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        head = make_repo(root / 'head')
        self.store = st.JobStore(root / 'jobs', lease_seconds=30)
        self.status, _ = self.store.create(request.build(adapter='godot', head=head, game='game/platformer',
                                                       routes=['routes/*.json'], specs='specs'))
        self.job = self.status['id']

    def test_cancel_on_ps_stops_marked_processes_without_signalling_a_recorded_group(self):
        machine = PsMachine()
        marker = f'{st.JOB_ENV}={self.job}'
        machine.add(1101, [marker])
        machine.add(1102, [marker], parent=1101)
        self.store.claim(self.job, 1101, 1101)
        with machine.installed(), mock.patch.object(st.os, 'kill', side_effect=machine.kill) as sent, \
                mock.patch.object(st.os, 'killpg', side_effect=AssertionError('unverified group signal')):
            result = self.store.cancel(self.job, grace_seconds=0)
        self.assertEqual(result['phase'], 'cancelled')
        self.assertEqual(cli.exit_code(result), 4)
        self.assertEqual(result['reasons'], ['cancelled on request'])
        self.assertEqual(sorted(call.args[0] for call in sent.call_args_list if call.args[1] != 0), [1101, 1102])

    def test_lost_worker_cleanup_reports_processes_stopped_by_ps(self):
        machine = PsMachine()
        machine.add(1102, [f'{st.JOB_ENV}={self.job}'])
        with machine.installed(), mock.patch.object(st.os, 'kill', side_effect=machine.kill), \
                mock.patch.object(st, 'process_handles', return_value=False):
            result = self.store.lose(self.job, 'worker lost', stage='executing', grace_seconds=0)
        self.assertEqual(result['phase'], 'failed')
        self.assertIn('stopped 1 process(es) it had started; by process number: this system has no process handles', result['reasons'])

    def test_permission_error_is_stated_and_cancel_command_stays_exit_four(self):
        machine = PsMachine()
        machine.add(1101, [f'{st.JOB_ENV}={self.job}'])
        out = io.StringIO()
        with machine.installed(), mock.patch.object(st.os, 'kill', side_effect=PermissionError(errno.EPERM, 'denied')), \
                contextlib.redirect_stdout(out):
            code = cli.main(['--jobs-root', str(self.store.root), 'cancel', self.job])
        self.assertEqual(code, 4)
        self.assertIn('could not stop', out.getvalue())
        self.assertIn('permission denied', out.getvalue())
        self.assertNotIn('stopped 1', out.getvalue())
        self.assertEqual(self.store.status(self.job)['phase'], 'cancelled')

    def test_missing_ps_is_stated_even_for_cancel_with_no_recorded_worker(self):
        with PsMachine().installed(), mock.patch.object(st.subprocess, 'run', side_effect=FileNotFoundError):
            result = self.store.cancel(self.job)
        self.assertEqual(cli.exit_code(result), 4)
        self.assertIn('could not look for', ' '.join(result['reasons']))
        self.assertIn('could not stop', ' '.join(result['reasons']))

    def test_a_denied_linux_group_does_not_escape_cancel_or_skip_marker_cleanup(self):
        self.store.claim(self.job, 1101, 1101)
        exists = Path.exists
        def has_proc(path):
            return True if str(path) == '/proc/self/environ' else exists(path)
        with mock.patch.object(Path, 'exists', has_proc), \
                mock.patch.object(st, 'stop_group', side_effect=PermissionError(errno.EPERM, 'denied')), \
                mock.patch.object(self.store, '_stop_what_it_started', return_value='left 1 running: could not stop it') as cleanup:
            result = self.store.cancel(self.job, grace_seconds=0)
        self.assertEqual(cli.exit_code(result), 4)
        self.assertIn('PermissionError', ' '.join(result['reasons']))
        self.assertIn('left 1 running', ' '.join(result['reasons']))
        cleanup.assert_called_once()


class GroupPermissionTest(unittest.TestCase):
    def test_a_gone_group_is_already_finished(self):
        with mock.patch.object(st.os, 'getpgid', return_value=9999), \
                mock.patch.object(st.os, 'killpg', side_effect=ProcessLookupError):
            self.assertIsNone(st.stop_group(1101, grace_seconds=0))

    def test_permission_error_followed_by_a_gone_group_is_not_an_error(self):
        with mock.patch.object(st.os, 'getpgid', return_value=9999), \
                mock.patch.object(st.os, 'killpg', side_effect=[PermissionError(errno.EPERM, 'denied'), ProcessLookupError]):
            self.assertIsNone(st.stop_group(1101, grace_seconds=0))

    def test_a_group_the_caller_cannot_signal_is_reported(self):
        with mock.patch.object(st.os, 'getpgid', return_value=9999), \
                mock.patch.object(st.os, 'killpg', side_effect=PermissionError(errno.EPERM, 'denied')):
            with self.assertRaisesRegex(st.StoreError, 'caller does not have permission'):
                st.stop_group(1101, grace_seconds=0)

    def test_a_visible_but_unsignalable_group_is_reported(self):
        with mock.patch.object(st.os, 'getpgid', return_value=9999), \
                mock.patch.object(st.os, 'killpg', side_effect=[PermissionError(errno.EPERM, 'denied'), None]):
            with self.assertRaisesRegex(st.StoreError, 'group still exists'):
                st.stop_group(1101, grace_seconds=0)

    def test_permission_error_while_waiting_is_not_a_claim_of_exit(self):
        with mock.patch.object(st.os, 'getpgid', return_value=9999), \
                mock.patch.object(st.os, 'killpg', side_effect=[None, PermissionError(errno.EPERM, 'denied')]):
            with self.assertRaisesRegex(st.StoreError, 'could not confirm'):
                st.stop_group(1101, grace_seconds=1)
