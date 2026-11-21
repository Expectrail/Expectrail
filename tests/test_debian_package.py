"""Build the desktop package from a real wheel and inspect it without installing it (#249)."""
import configparser
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from email.parser import BytesParser, Parser
from pathlib import Path

from tools.quickstart import ROOT, copy_checkout


class DebianPackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [name for name in ('pip', 'setuptools', 'installer')
                   if importlib.util.find_spec(name) is None]
        if not shutil.which('dpkg-deb'):
            missing.append('dpkg-deb')
        python = Path('/usr/bin/python3')
        probe = ("import sys; sys.exit(sys.version_info < (3, 12) or "
                 "'/usr/lib/python3/dist-packages' not in sys.path)")
        if (sys.platform != 'linux' or not python.is_file()
                or subprocess.run([python, '-I', '-c', probe]).returncode != 0):
            missing.append('a Debian-family system Python 3.12+')
        if missing:
            reason = 'Building the desktop package requires ' + ', '.join(missing)
            if os.environ.get('EXPECTRAIL_PACKAGE_TESTS') == 'required':
                raise AssertionError(reason)
            raise unittest.SkipTest(reason)

        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.work = Path(temp.name)
        source = cls.work / 'checkout'
        copy_checkout(ROOT, source)
        subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation',
                        '--no-index', '-q', '-w', str(cls.work), '.'], cwd=source, check=True)
        cls.wheel, = cls.work.glob('*.whl')
        output = cls.work / 'desktop packages'
        subprocess.run([sys.executable, str(ROOT / 'tools/build_deb.py'), '--output-dir', output,
                        cls.wheel], cwd=cls.work, check=True, umask=0o077)
        cls.deb, = output.glob('*.deb')
        cls.extracted = cls.work / 'extracted'
        subprocess.run(['dpkg-deb', '--raw-extract', cls.deb, cls.extracted], check=True)
        cls.site = cls.extracted / 'usr/lib/python3/dist-packages'

    def test_control_matches_the_wheel_and_the_linux_replay_tools(self):
        with zipfile.ZipFile(self.wheel) as wheel:
            metadata, = [name for name in wheel.namelist() if name.endswith('.dist-info/METADATA')]
            wheel_metadata = BytesParser().parsebytes(wheel.read(metadata))
        control_dir = self.extracted / 'DEBIAN'
        self.assertEqual({p.name for p in control_dir.iterdir()}, {'control'})
        control = Parser().parsestr((control_dir / 'control').read_text())
        self.assertEqual((control['Package'], control['Version'], control['Architecture']),
                         (wheel_metadata['Name'], wheel_metadata['Version'], 'amd64'))
        self.assertEqual(self.deb.name, f"expectrail_{control['Version']}_amd64.deb")
        self.assertRegex(wheel_metadata['Requires-Python'], r'^>=[0-9]+(?:\.[0-9]+)+$')
        floor = wheel_metadata['Requires-Python'].removeprefix('>=')
        depends = {item.strip() for item in control['Depends'].split(',')}
        self.assertTrue({f'python3 (>= {floor})', 'python3-tk', 'xdg-utils', 'xvfb', 'xauth',
                         'libgl1-mesa-dri', 'libglx-mesa0', 'patch', 'curl', 'unzip',
                         'ca-certificates'} <= depends)
        self.assertIn('bubblewrap', control['Recommends'].split(', '))

    def test_wheel_payload_is_readable_and_matches_byte_for_byte(self):
        with zipfile.ZipFile(self.wheel) as wheel:
            payload = {name for name in wheel.namelist() if not name.endswith('/')}
            installed_files = {path.relative_to(self.site).as_posix()
                               for path in self.site.rglob('*') if path.is_file()}
            self.assertEqual(installed_files, payload)
            for name in payload:
                if name.endswith('.dist-info/RECORD'):
                    continue
                installed = self.site / name
                with self.subTest(file=name):
                    self.assertEqual(installed.read_bytes(), wheel.read(name))
                    self.assertTrue(installed.stat().st_mode & 0o004)
        for directory in self.extracted.rglob('*'):
            if directory.is_dir():
                self.assertTrue(directory.stat().st_mode & 0o001, directory)
        command = self.extracted / 'usr/bin/expectrail'
        self.assertEqual(command.read_bytes().splitlines()[0], b'#!/usr/bin/python3')
        self.assertTrue(command.stat().st_mode & 0o001)

    def test_menu_entry_loads_the_extracted_app_with_the_system_interpreter(self):
        desktop = configparser.ConfigParser(interpolation=None)
        desktop.read(self.extracted / 'usr/share/applications/expectrail.desktop')
        entry = desktop['Desktop Entry']
        self.assertEqual((entry['Type'], entry['Name'], entry.getboolean('Terminal')),
                         ('Application', 'Expectrail', False))
        self.assertEqual(entry['Exec'].split(),
                         ['/usr/bin/python3', '-I', '-m', 'expectrail.cli', 'app', '--open-browser'])
        # Redirect just the system package directory into the extracted root. A shadow
        # package in the launch directory would raise if isolated mode were dropped.
        shadow = self.work / 'expectrail'
        shadow.mkdir()
        (shadow / '__init__.py').write_text('raise AssertionError("imported from cwd")')
        code = """
import runpy, sys
from pathlib import Path
sys.dont_write_bytecode = True
site = sys.argv.pop(1)
sys.path[sys.path.index('/usr/lib/python3/dist-packages')] = site
import expectrail
assert Path(expectrail.__file__).is_relative_to(site)
runpy.run_module('expectrail.cli', run_name='__main__', alter_sys=True)
"""
        python, isolated, _, _, *args = entry['Exec'].split()
        done = subprocess.run([python, isolated, '-c', code, self.site, *args, '--help'],
                              cwd=self.work, capture_output=True, text=True, timeout=15)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('--open-browser', done.stdout)
