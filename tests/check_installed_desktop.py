"""Exercise the installed desktop entry and its browser handoff on a disposable Ubuntu host."""
import configparser
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener


def receive_page(address):
    # The app passes a local access token in the address. Keep it and the page in memory.
    url = urlsplit(address)
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.path != '/':
        raise SystemExit('Expected a loopback app address')
    with build_opener(ProxyHandler({})).open(address, timeout=5) as response:
        page = response.read()
    if not all(field in page for field in (b'id="before"', b'id="after"', b'>Check folders<')):
        raise SystemExit('The project selection page did not open')
    Path('page-opened').touch()


def check_install():
    desktop = configparser.ConfigParser(interpolation=None)
    desktop.read('/usr/share/applications/expectrail.desktop')
    entry = desktop['Desktop Entry']
    if entry.getboolean('Terminal'):
        raise SystemExit('The menu entry requests a terminal')
    with tempfile.TemporaryDirectory() as work:
        # A stand-in for the default browser receives the application's normal handoff.
        browser = shlex.join([sys.executable, '-I', str(Path(__file__).resolve()), '%s'])
        env = {**os.environ, 'BROWSER': browser, 'HOME': work}
        app = subprocess.Popen(shlex.split(entry['Exec']), cwd=work, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 15
            while not (Path(work) / 'page-opened').exists():
                if app.poll() is not None or time.monotonic() >= deadline:
                    raise SystemExit('The installed launcher did not open the project selection page')
                time.sleep(0.1)
        finally:
            app.terminate()
            app.wait(timeout=5)
    print('The installed desktop command opened the Before and After project selection page.')


if __name__ == '__main__':
    if len(sys.argv) == 2:
        receive_page(sys.argv[1])
    else:
        check_install()
