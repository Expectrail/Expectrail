"""Prerequisites for integration tests: missing tools skip locally and fail required CI jobs."""
import importlib.util
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import unittest

from agents.sandbox import bwrap_problem


def display_problem():
    if sys.platform.startswith('linux') and shutil.which('xvfb-run') is None:
        return 'xvfb-run is not installed; the drawn replay needs a virtual display'
    return None


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
