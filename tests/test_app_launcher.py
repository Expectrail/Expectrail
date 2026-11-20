"""Installed launchers point to the venv and expose no session token."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from expectrail import app


class LauncherTest(unittest.TestCase):
    def launch(self, platform):
        with tempfile.TemporaryDirectory(prefix="expectrail home ' $% ") as tmp:
            home = Path(tmp)
            python = home / '.local/share/expectrail/app-env/bin/python'
            python.parent.mkdir(parents=True)
            capture = home / 'started.json'
            python.write_text(f'#!{sys.executable}\nimport json, sys\n'
                              f'with open({str(capture)!r}, "w") as out:\n'
                              '    json.dump(sys.argv, out)\n')
            python.chmod(0o700)
            with mock.patch.object(app.sys, 'executable', str(python)), \
                 mock.patch.object(app.sys, 'platform', platform), \
                 mock.patch.object(app.Path, 'home', return_value=home), \
                 mock.patch.dict(os.environ, {'XDG_DATA_HOME': str(home / 'shared data')}):
                installed = app.install_launcher()
                self.assertEqual(app.install_launcher(), installed)
            if platform == 'linux':
                self.assertEqual(installed, home / 'shared data/applications/expectrail.desktop')
                self.assertIn('Terminal=false', installed.read_text())
                command = ['gio', 'launch', str(installed)]
            else:
                self.assertEqual(installed, home / 'Applications/Expectrail.command')
                command = [str(installed)]
            self.assertTrue(os.access(installed, os.X_OK))
            self.assertNotIn('token=', installed.read_text())
            done = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(done.returncode, 0, done.stderr)
            deadline = time.monotonic() + 5
            while not capture.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertEqual(json.loads(capture.read_text()),
                             [str(python), '-I', '-m', 'expectrail.cli', 'app', '--open-browser'])

    def test_linux_desktop_entry_launches_the_installed_python(self):
        if sys.platform != 'linux' or shutil.which('gio') is None:
            self.skipTest('Linux gio is needed to launch the desktop entry')
        self.launch('linux')

    def test_command_file_runs_with_a_shell_and_paths_with_spaces(self):
        if os.name != 'posix':
            self.skipTest('A POSIX shell is needed to run the macOS command file')
        self.launch('darwin')
