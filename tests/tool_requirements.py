"""Prerequisites for integration tests: missing tools skip locally and fail required CI jobs."""
import importlib.util
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

from agents.sandbox import bwrap_problem


def display_problem():
    from expectrail import doctor
    if sys.platform.startswith('linux') or sys.platform == 'darwin':
        check = doctor.display()
        return check.found if check.status == 'missing' else None
    return None


def executable(name):
    if shutil.which(name) is None:
        raise unittest.SkipTest(f'{name} is not installed; this integration needs it on PATH')


def godot_binary(*, switch='EXPECTRAIL_ENGINE_TESTS'):
    """Use an installed engine, never download one just to discover tests."""
    from harness import run as hr
    named = os.environ.get('EXPECTRAIL_GODOT')
    if named:
        candidates = [Path(named)]
    else:
        candidates = ([hr.REPO / 'tools/godot_mac/Godot.app/Contents/MacOS/Godot'] if sys.platform == 'darwin' else
                      [hr.tools_dir() / 'godot' / f'Godot_v{hr.GODOT_VERSION}_linux.x86_64'])
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    versions = []
    if not named:
        for name in ('godot4', 'godot'):
            found = shutil.which(name)
            if found:
                version = subprocess.run([found, '--version'], capture_output=True, text=True, timeout=15)
                if version.returncode:
                    raise AssertionError(f'{name} --version failed with exit {version.returncode}')
                said = version.stdout.strip().splitlines()[-1] if version.stdout.strip() else ''
                want = hr.GODOT_VERSION.replace('-', '.')
                if said == want or said.startswith(want + '.'):
                    return Path(found)
                versions.append(said or 'unknown')
    why = f'Godot {hr.GODOT_VERSION} is not installed at its configured/cache path or on PATH; see expectrail doctor'
    if versions:
        why += '; PATH has a different version: ' + ', '.join(versions)
    if os.environ.get(switch) == 'required':
        raise AssertionError(f'{switch}=required: {why}')
    raise unittest.SkipTest(why)


def unix_problem():
    if not hasattr(socket, 'AF_UNIX'):
        return 'AF_UNIX sockets are not supported on this system'
    try:
        with tempfile.TemporaryDirectory() as tmp, socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            address = str(Path(tmp) / 's')
            server.bind(address)
            server.listen(1)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect(address)
    except OSError as exc:
        return f'AF_UNIX sockets are unavailable: {exc}'
    return None


def chromium_problem():
    if importlib.util.find_spec('playwright') is None:
        return 'Playwright is not installed; its Chromium executable is required'
    from playwright.sync_api import Error, sync_playwright
    from harness.web.run import CHROMIUM_ARGS, game_env

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=CHROMIUM_ARGS, env=game_env())
            browser.close()
    except Error as exc:
        # Only known missing installation pieces are optional. A crash or a test bug still fails.
        for line in str(exc).splitlines():
            if "Executable doesn't exist at" in line:
                return 'Playwright Chromium unavailable: ' + line.strip()
        if 'Host system is missing dependencies' in str(exc):
            return 'Playwright Chromium unavailable: host system is missing browser dependencies'
        raise
    return None


TOOLS = {
    'xvfb-run': ('EXPECTRAIL_ENGINE_TESTS', 'required', display_problem),
    'AF_UNIX': ('EXPECTRAIL_GATEWAY_TESTS', 'required', unix_problem),
    'Bubblewrap': ('EXPECTRAIL_REQUIRE_BWRAP', '1', bwrap_problem),
    'Playwright Chromium': ('EXPECTRAIL_WEB_TESTS', 'required', chromium_problem),
}


def require_tool(tool):
    switch, value, probe = TOOLS[tool]
    why = probe()
    if why is not None:
        if os.environ.get(switch) == value:
            raise AssertionError(f'{switch}={value}: {why}')
        raise unittest.SkipTest(why)
