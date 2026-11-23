"""Missing integrations name the prerequisite; present tools and unexpected bugs do not skip."""
import contextlib
import ctypes
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from expectrail import doctor
from agents import sandbox
from harness import sandbox as replay
from tests import tool_requirements as req


class KeylessIntegrationTest(unittest.TestCase):
    def test_real_project_fixture_clears_and_restores_vision_settings(self):
        from tests.test_second_project import RealGodotTest

        class Probe(RealGodotTest):
            pass

        with mock.patch.dict(os.environ, MODEL_API_KEY='not-a-real-key', EXPECTRAIL_SAM_USD_CAP='1'), \
                mock.patch.object(req, 'godot_binary', return_value=Path('/stand-in/engine')), \
                mock.patch.object(req, 'require_tool'):
            try:
                Probe.setUpClass()
                self.assertEqual(os.environ['MODEL_API_KEY'], '')
                self.assertEqual(os.environ['EXPECTRAIL_SAM_USD_CAP'], '')
                self.assertEqual(os.environ['EXPECTRAIL_GODOT'], '/stand-in/engine')
            finally:
                Probe.doClassCleanups()
            self.assertEqual(os.environ['MODEL_API_KEY'], 'not-a-real-key')
            self.assertEqual(os.environ['EXPECTRAIL_SAM_USD_CAP'], '1')


class NativeDisplayTest(unittest.TestCase):
    def test_online_missing_and_refused_display_and_unavailable_framework(self):
        for code, count, status, words in ((0, 1, 'ok', 'online display'), (0, 0, 'missing', 'no online display'),
                                          (1000, 0, 'missing', 'refused')):
            core = mock.Mock()
            def answer(_size, _displays, number):
                number._obj.value = count
                return code
            core.CGGetOnlineDisplayList.side_effect = answer
            with self.subTest(code=code, count=count), mock.patch.object(doctor.sys, 'platform', 'darwin'), \
                    mock.patch.object(ctypes, 'CDLL', return_value=core):
                found = doctor.display()
                self.assertEqual(found.status, status)
                self.assertTrue(found.required)
                self.assertTrue(found.run)
                self.assertIn(words, found.found)
                self.assertEqual(doctor.problems(doctor.document([found])), [])
                if status == 'missing':
                    self.assertIn('graphical macOS session', found.fix)
                    self.assertIn('macOS', req.display_problem())
                    with self.assertRaisesRegex(unittest.SkipTest, 'macOS'):
                        with mock.patch.dict(os.environ, EXPECTRAIL_ENGINE_TESTS=''):
                            req.require_tool('xvfb-run')
                else:
                    self.assertIsNone(req.display_problem())
                    req.require_tool('xvfb-run')
        with mock.patch.object(ctypes, 'CDLL', side_effect=OSError('unavailable')):
            self.assertIn('CoreGraphics (OSError)', doctor.macos_display_problem())

    def test_linux_missing_display_and_godot_keep_actionable_fixes(self):
        with mock.patch.object(doctor.sys, 'platform', 'linux'), mock.patch.object(doctor.shutil, 'which', return_value=None):
            found = doctor.display()
            self.assertEqual((found.status, found.required), ('missing', True))
            self.assertIn('xvfb-run', found.found)
            self.assertIn('apt-get install xvfb', found.fix)
        with mock.patch.object(doctor, '_where_godot_would_be', return_value=None):
            engine, path = doctor.godot(fetch=False)
        self.assertIsNone(path)
        self.assertIn('Godot', engine.found)
        self.assertIn('EXPECTRAIL_GODOT', engine.fix)
        self.assertIn('without --no-fetch', engine.fix)
        waiting = doctor.opengl(None, found)
        self.assertEqual(waiting.status, 'skipped')
        self.assertIn('Godot and a display', waiting.found)

    def test_display_wrapper_is_not_enough_without_xvfb_or_xauth(self):
        for absent, package in (('Xvfb', 'xvfb'), ('xauth', 'xauth')):
            with self.subTest(absent=absent), mock.patch.object(doctor.sys, 'platform', 'linux'), \
                    mock.patch.object(doctor.shutil, 'which', side_effect=lambda name: None if name == absent else '/usr/bin/'+name):
                found = doctor.display()
                self.assertEqual(found.status, 'missing')
                self.assertIn(absent + ' is not installed', found.found)
                self.assertEqual(found.fix, 'sudo apt-get install ' + package)
                self.assertEqual(req.display_problem(), found.found)
        with mock.patch.object(doctor.sys, 'platform', 'linux'), mock.patch.object(doctor.shutil, 'which', return_value='/available'):
            self.assertEqual(doctor.display().status, 'ok')
            self.assertIsNone(req.display_problem())

    def test_real_doctor_assertion_keeps_linux_renderer_and_accepts_native_drawing(self):
        from tests import test_doctor
        found = [doctor._ok('godot', 'Godot', 'Godot 4.7.2.stable'),
                 doctor._ok('opengl', 'OpenGL', 'the engine drew a frame with a native device')]
        case = test_doctor.RealEngineTest('test_the_real_engine_at_the_pinned_version_draws_a_frame')
        with mock.patch.object(doctor, 'for_run', return_value=found), \
                mock.patch('expectrail.orchestrator.engines.GodotGate._tools', return_value=[]):
            with mock.patch.object(doctor.sys, 'platform', 'darwin'):
                case.test_the_real_engine_at_the_pinned_version_draws_a_frame()
            with mock.patch.object(doctor.sys, 'platform', 'linux'):
                with self.assertRaisesRegex(AssertionError, 'llvmpipe'):
                    case.test_the_real_engine_at_the_pinned_version_draws_a_frame()


class BrowserDoctorTest(unittest.TestCase):
    def test_missing_package_executable_dependencies_failure_and_present_browser(self):
        with mock.patch.dict(sys.modules, {'playwright.sync_api': None}):
            found = doctor.chromium()
            self.assertIn('Playwright is not installed', found.found)
            self.assertIn('requirements-web.txt', found.fix)
        class Error(Exception):
            pass
        start = mock.MagicMock()
        api = types.SimpleNamespace(Error=Error, sync_playwright=start)
        with mock.patch.dict(sys.modules, {'playwright.sync_api': api}):
            launch = start.return_value.__enter__.return_value.chromium.launch
            for error, words in (("Executable doesn't exist at /private/SECRET", 'not installed'),
                                 ('Host system is missing dependencies SECRET', 'system dependencies'),
                                 ('crashed SECRET', 'could not start')):
                with self.subTest(error=error):
                    launch.side_effect = Error(error)
                    found = doctor.chromium()
                    self.assertEqual((found.id, found.status, found.required), ('chromium', 'missing', False))
                    self.assertIn(words, found.found)
                    self.assertIn('playwright install chromium', found.fix)
                    doc = doctor.document([found])
                    self.assertEqual(doctor.problems(doc), [])
                    self.assertNotIn('SECRET', json.dumps(doc) + doctor.text([found]))
            launch.side_effect = None
            found = doctor.chromium()
            self.assertEqual(found.status, 'ok')
            launch.return_value.close.assert_called_once()
            launch.return_value.new_page.assert_not_called()

    def test_any_failure_of_the_optional_browser_probe_is_missing_never_a_crash(self):
        # The guard's finding on #479: the Playwright driver can raise a plain Exception, and a broken
        # install can fail on import with something other than ImportError.
        class Error(Exception):
            pass
        start = mock.MagicMock()
        start.return_value.__enter__.side_effect = Exception("Connection closed while reading from the driver SECRET")
        with mock.patch.dict(sys.modules, {'playwright.sync_api': types.SimpleNamespace(Error=Error, sync_playwright=start)}):
            found = doctor.chromium()
        self.assertEqual((found.id, found.status, found.required), ('chromium', 'missing', False))
        self.assertIn('could not start (Exception)', found.found)
        self.assertNotIn('SECRET', json.dumps(doctor.document([found])))
        self.assertEqual(doctor.document([found])['ok'], True)
        class Broken:
            def __getattr__(self, name):
                raise RuntimeError("broken install SECRET")
        with mock.patch.dict(sys.modules, {'playwright.sync_api': Broken()}):
            found = doctor.chromium()
        self.assertEqual((found.status, found.required), ('missing', False))
        self.assertIn('could not be imported (RuntimeError)', found.found)

    def test_doctors_list_includes_the_optional_browser_probe(self):
        from tests import test_doctor
        machine = test_doctor.Machine()
        machine.setUp()
        try:
            with mock.patch.object(doctor, 'chromium', return_value=doctor._missing('chromium', 'Playwright Chromium',
                                         'Chromium is missing', 'python3 -m playwright install chromium', required=False)):
                found = doctor.checks(fetch=False)
            text = doctor.text(found)
            self.assertIn('Chromium is missing', text)
            self.assertIn('playwright install chromium', text)
            self.assertFalse(doctor.missing(found))
            self.assertEqual(doctor.problems(doctor.document(found)), [])
        finally:
            machine.doCleanups()


class SandboxRefusalTest(unittest.TestCase):
    def test_doctor_missing_and_refused_bubblewrap_and_native_limitation(self):
        for platform, why, fix in (('linux', 'bubblewrap (bwrap) is not installed', 'apt-get install bubblewrap'),
                                   ('linux', 'bubblewrap could not start: Operation not permitted', 'user namespaces'),
                                   ('darwin', 'bubblewrap runs on Linux only', 'use a Linux host')):
            with self.subTest(platform=platform, why=why), mock.patch.object(doctor.sys, 'platform', platform), \
                    mock.patch.object(replay, 'probe', return_value=(None, why)):
                for isolated in (False, True):
                    found = doctor.sandbox(isolated)
                    self.assertEqual((found.status, found.required), ('missing', isolated))
                    self.assertEqual(found.found, why)
                    self.assertIn(fix, found.fix)
                    self.assertEqual(doctor.problems(doctor.document([found])), [])
                with self.assertRaisesRegex(replay.SandboxError, 'bubblewrap'):
                    replay.choose('require', False)

    def test_fixer_required_check_refuses_missing_denied_and_disappearing_tool(self):
        for outcome in ('missing', PermissionError('Operation not permitted'), FileNotFoundError('removed'),
                        subprocess.CompletedProcess([], 1, '', 'bwrap: NETLINK_ROUTE: Operation not permitted')):
            with self.subTest(outcome=outcome), mock.patch.object(sandbox, '_BWRAP_WARNED', False), \
                    mock.patch.object(sandbox.shutil, 'which', side_effect=lambda name: '/bin/bwrap' if name == 'bwrap' and outcome != 'missing' else None), \
                    mock.patch.object(sandbox.subprocess, 'run') as run, \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                if isinstance(outcome, Exception):
                    run.side_effect = outcome
                else:
                    run.return_value = outcome
                self.assertEqual(sandbox.main(['--require-sandbox']), 2)
                self.assertIn('Bubblewrap', err.getvalue())
                self.assertIn('sandbox unavailable', err.getvalue())
                if outcome == 'missing':
                    run.assert_not_called()
                else:
                    self.assertEqual(run.call_count, 1)  # only the probe; never the fixer


class EnginePrerequisiteTest(unittest.TestCase):
    def test_missing_godot_skips_locally_fails_required_and_never_fetches(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, EXPECTRAIL_GODOT=tmp+'/missing'), \
                mock.patch('harness.run.find_godot', side_effect=AssertionError('no downloads')):
            for required in ('', 'required'):
                with mock.patch.dict(os.environ, EXPECTRAIL_ENGINE_TESTS=required):
                    with self.assertRaisesRegex(AssertionError if required else unittest.SkipTest, 'Godot'):
                        req.godot_binary()
            engine = Path(tmp)/'present';engine.write_text('stand-in');engine.chmod(0o755)
            with mock.patch.dict(os.environ, EXPECTRAIL_GODOT=str(engine), EXPECTRAIL_ENGINE_TESTS=''):
                self.assertEqual(req.godot_binary(), engine)

    def test_macos_bundle_cache_and_path_are_recognised(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, EXPECTRAIL_GODOT='', EXPECTRAIL_TOOLS=''), \
                mock.patch('harness.run.REPO', Path(tmp)), mock.patch.object(req.sys, 'platform', 'darwin'), \
                mock.patch.object(req.shutil, 'which', return_value=None):
            engine = Path(tmp)/'tools/godot_mac/Godot.app/Contents/MacOS/Godot'
            engine.parent.mkdir(parents=True);engine.touch();engine.chmod(0o755)
            self.assertEqual(req.godot_binary(), engine)
            engine.unlink()
            on_path=Path(tmp)/'godot4';on_path.touch();on_path.chmod(0o755)
            with mock.patch.object(req.shutil, 'which', return_value=str(on_path)), \
                    mock.patch.object(req.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '4.7.2.stable.official\n', '')):
                self.assertEqual(req.godot_binary(), on_path)

    def test_shell_tools_skip_only_when_absent(self):
        for tool in ('timeout', 'sha512sum', 'unzip'):
            with self.subTest(tool=tool), mock.patch.object(req.shutil, 'which', return_value=None):
                with self.assertRaisesRegex(unittest.SkipTest, tool):
                    req.executable(tool)
            with mock.patch.object(req.shutil, 'which', return_value='/bin/'+tool):
                req.executable(tool)

    def test_wrong_path_version_is_not_the_pinned_tool_and_crashes_are_not_skips(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, EXPECTRAIL_GODOT='', EXPECTRAIL_TOOLS=tmp, EXPECTRAIL_ENGINE_TESTS=''), \
                mock.patch.object(req.sys, 'platform', 'linux'), mock.patch.object(req.shutil, 'which', return_value='/bin/godot'), \
                mock.patch.object(req.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '4.6.3.stable', '')) as run:
            with self.assertRaisesRegex(unittest.SkipTest, 'Godot 4.7.2-stable.*different version: 4.6.3'):
                req.godot_binary()
            with mock.patch.dict(os.environ, EXPECTRAIL_ENGINE_TESTS='required'):
                with self.assertRaisesRegex(AssertionError, 'Godot 4.7.2-stable'):
                    req.godot_binary()
            run.return_value = subprocess.CompletedProcess([], -6, '', '')
            with self.assertRaisesRegex(AssertionError, 'exit -6'):
                req.godot_binary()


class OpenPathTest(unittest.TestCase):
    def test_parent_aliases_match_without_turning_a_refused_link_open_into_a_target_open(self):
        from tests.test_orchestrator import canonical_open_path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            real = root / 'real'; real.mkdir()
            alias = root / 'alias'; alias.symlink_to(real, target_is_directory=True)
            target = real / 'target.json'; target.write_text('{}')
            link = real / 'two.json'; link.symlink_to(target)
            self.assertEqual(canonical_open_path(alias / 'target.json'), str(target))
            self.assertEqual(canonical_open_path(alias / 'two.json'), str(link))
            self.assertNotEqual(canonical_open_path(alias / 'two.json'), str(target))

class NativeDrawingFixTest(unittest.TestCase):
    def test_failed_native_drawing_names_a_native_fix(self):
        with mock.patch.object(doctor.sys, 'platform', 'darwin'), \
                mock.patch('harness.run.godot_cmd', return_value=['stand-in']), \
                mock.patch.object(doctor.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')):
            found = doctor.opengl(Path('/stand-in/godot'), doctor._ok('display', 'display', 'online'))
        self.assertEqual((found.status, found.required), ('missing', True))
        self.assertIn('graphical macOS session', found.fix)
        self.assertNotIn('apt-get', found.fix)
        self.assertEqual(doctor.problems(doctor.document([found])), [])
