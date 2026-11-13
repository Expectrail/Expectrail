"""Tool absence is explicit, required jobs fail, and namespace probes match real commands (#365)."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import types
import unittest
from unittest import mock

from agents import sandbox
from harness import sandbox as replay


def namespaces(cmd):
    return {a for a in cmd[:cmd.index('--')] if a.startswith(('--unshare-', '--share-'))}


class ProbeTest(unittest.TestCase):
    def test_fixer_probe_matches_offline_and_gateway_namespaces(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(sandbox.shutil, 'which', return_value='/usr/bin/bwrap'), \
                mock.patch.object(sandbox.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertTrue(sandbox._bwrap_usable())
            probe = run.call_args.args[0]
            work = Path(tmp)
            gateway = mock.Mock(dir=work, bridge_argv=lambda argv: argv)
            for kw in ({'network': False}, {'network': True, 'gateway': gateway}):
                actual = sandbox._bwrap_cmd(work, ['true'], **kw)
                self.assertEqual(namespaces(probe), namespaces(actual))
            self.assertIn('--unshare-net', namespaces(probe))

    def test_refusal_is_reported_once_and_detection_falls_back(self):
        err = 'bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted'
        with mock.patch.object(sandbox.shutil, 'which', side_effect=lambda name: '/usr/bin/bwrap' if name == 'bwrap' else None), \
                mock.patch.object(sandbox.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', err)), \
                mock.patch.object(sandbox, '_BWRAP_WARNED', False, create=True), contextlib.redirect_stderr(io.StringIO()) as log:
            self.assertEqual(sandbox.detect_sandbox(), 'none')
            self.assertEqual(sandbox.detect_sandbox(), 'none')
        self.assertEqual(log.getvalue().count('NETLINK_ROUTE'), 1)
        self.assertIn('Bubblewrap', log.getvalue())

    def test_missing_failed_timed_out_and_working_probe(self):
        with mock.patch.object(sandbox.shutil, 'which', return_value=None), \
                mock.patch.object(sandbox.subprocess, 'run') as run:
            self.assertIn('not installed', sandbox.bwrap_problem())
            run.assert_not_called()
        for response, words in ((OSError('refused'), 'refused'),
                                (subprocess.TimeoutExpired('bwrap', 15), 'TimeoutExpired'),
                                (subprocess.CompletedProcess([], 2, '', ''), 'exit 2'),
                                (subprocess.CompletedProcess([], 0, '', ''), None)):
            with self.subTest(response=response), mock.patch.object(sandbox.shutil, 'which', return_value='/usr/bin/bwrap'), \
                    mock.patch.object(sandbox.subprocess, 'run', **({'side_effect': response} if isinstance(response, Exception)
                                                                 else {'return_value': response})):
                why = sandbox.bwrap_problem()
                self.assertIsNone(why) if words is None else self.assertIn(words, why)

    def test_docker_remains_the_next_choice(self):
        with mock.patch.object(sandbox.shutil, 'which', side_effect=lambda name: '/usr/bin/' + name), \
                mock.patch.object(sandbox.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 1, '', 'refused'),
                                                                         subprocess.CompletedProcess([], 0)]), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(sandbox.detect_sandbox(), 'docker')

    def test_replay_probe_already_uses_the_real_namespace_options(self):
        replay.probe.cache_clear()
        self.addCleanup(replay.probe.cache_clear)
        with mock.patch.object(replay.sys, 'platform', 'linux'), \
                mock.patch.object(replay.shutil, 'which', return_value='/usr/bin/bwrap'), \
                mock.patch.object(replay.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 0, 'bubblewrap test'),
                                                                        subprocess.CompletedProcess([], 0, '', '')]) as run, \
                tempfile.TemporaryDirectory() as tmp:
            tool, why = replay.probe(False)
            self.assertIsNone(why)
            probe = run.call_args.args[0]
            actual = replay.command(tool, ['true'], game=Path(tmp), out=Path(tmp))
            self.assertEqual(namespaces(probe), namespaces(actual))
            self.assertIn('--unshare-net', namespaces(probe))


class RequirementsTest(unittest.TestCase):
    def test_missing_tools_skip_or_fail_when_required_and_present_tools_run(self):
        from tests import tool_requirements as req

        for tool, (switch, value, _probe) in req.TOOLS.items():
            for required in (False, True):
                with self.subTest(tool=tool, required=required), \
                        mock.patch.dict(os.environ, {switch: value if required else ''}), \
                        mock.patch.dict(req.TOOLS, {tool: (switch, value, lambda: 'missing ' + tool)}):
                    with self.assertRaisesRegex(AssertionError if required else unittest.SkipTest, tool):
                        req.require_tool(tool)
            with mock.patch.dict(req.TOOLS, {tool: (switch, value, lambda: None)}):
                req.require_tool(tool)

    def test_display_and_unix_socket_checks_name_the_cause(self):
        from tests import tool_requirements as req

        with mock.patch.object(req.sys, 'platform', 'linux'), mock.patch.object(req.shutil, 'which', return_value=None):
            self.assertIn('xvfb-run', req.display_problem())
        with mock.patch.object(req.sys, 'platform', 'darwin'), mock.patch.object(req.shutil, 'which', return_value=None):
            self.assertIsNone(req.display_problem())
        with mock.patch.object(req.socket, 'socket', side_effect=PermissionError('Operation not permitted')):
            self.assertIn('AF_UNIX', req.unix_problem())
            self.assertIn('Operation not permitted', req.unix_problem())
        with mock.patch.object(req.socket, 'socket') as socket:
            self.assertIsNone(req.unix_problem())
            socket.return_value.__enter__.return_value.bind.assert_called_once()
            socket.return_value.__enter__.return_value.connect.assert_called_once()

    def test_chromium_absence_is_optional_but_other_browser_errors_are_not_hidden(self):
        from tests import tool_requirements as req
        class Error(Exception):
            pass

        with mock.patch.object(req.importlib.util, 'find_spec', return_value=None):
            self.assertIn('Playwright', req.chromium_problem())
        start = mock.MagicMock()
        api = types.SimpleNamespace(Error=Error, sync_playwright=start)
        with mock.patch.dict(sys.modules, {'playwright': types.ModuleType('playwright'), 'playwright.sync_api': api}), \
                mock.patch.object(req.importlib.util, 'find_spec', return_value=True):
            launch = start.return_value.__enter__.return_value.chromium.launch
            launch.side_effect = Error("Executable doesn't exist at /missing/chromium")
            self.assertIn('/missing/chromium', req.chromium_problem())
            launch.side_effect = Error('unrelated browser bug')
            with self.assertRaisesRegex(Error, 'unrelated browser bug'):
                req.chromium_problem()
            launch.side_effect = None
            self.assertIsNone(req.chromium_problem())
            launch.return_value.close.assert_called_once()

    def test_ci_requires_the_tools_in_the_jobs_that_supply_them(self):
        import yaml

        jobs = yaml.safe_load((Path(__file__).resolve().parent.parent / '.github/workflows/ci.yml').read_text())['jobs']
        for job, module, switch, value in (
                ('capture-smoke', 'tests.test_event_input', 'EXPECTRAIL_ENGINE_TESTS', 'required'),
                ('capture-smoke', 'tests.test_pause_input', 'EXPECTRAIL_ENGINE_TESTS', 'required'),
                ('agents-sandbox', 'tests.test_guard.BwrapGuardTest', 'EXPECTRAIL_REQUIRE_BWRAP', '1'),
                ('web-capture', 'tests.test_web', 'EXPECTRAIL_WEB_TESTS', 'required'),
                ('test', 'unittest discover', 'EXPECTRAIL_GATEWAY_TESTS', 'required'),
                ('package', 'unittest discover', 'EXPECTRAIL_GATEWAY_TESTS', 'required')):
            with self.subTest(job=job):
                step = next(s for s in jobs[job]['steps'] if module in s.get('run', ''))
                self.assertEqual(step.get('env', {}).get(switch), value)
