"""A loopback-only, token-authenticated front end for the existing job orchestrator."""
from __future__ import annotations

import argparse
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import threading
from urllib.parse import parse_qs, unquote, urlsplit

from expectrail import app_page
from expectrail.orchestrator import request as req, runner
from expectrail.orchestrator.store import JobStore, StoreError, UnknownJob, FINAL

LIMIT = 64 * 1024


def field(body, name, default=None):
    value = body.get(name, default)
    if not isinstance(value, str) or not value.strip() or '\0' in value:
        raise ValueError(f'Enter {name} as text. Nothing was run.')
    return value.strip()


def build(body, *, inspect=False):
    head = Path(field(body, 'folder' if inspect else 'after')).expanduser()
    return req.build(adapter='godot', head=head,
                     base=None if inspect else Path(field(body, 'before')).expanduser(),
                     game=field(body, 'game', '.'),
                     routes=field(body, 'routes', 'routes/*.json').replace(',', ' ').split(),
                     specs=field(body, 'specs', 'specs'))


def inspect_project(body):
    doc = build(body, inspect=True)
    root = Path(doc['head']['checkout'])
    game = root / doc['project']['game']
    from harness.adapters import get

    found = root.is_dir() and get('godot').is_project(game)
    checks = req.read_checks(doc)
    help_text = []
    if not root.is_dir():
        help_text.append('This folder does not exist. Paste the full path to an existing folder.')
    elif not found:
        help_text.append('No Godot project found. Choose the folder containing project.godot, '
                         'or set the game folder below.')
    if not checks.routes:
        help_text.append('No usable routes found. Choose your route files in the settings below. '
                         'If you have none, ask your game developer to record routes for these checks.')
    if not checks.specs:
        help_text.append('No approved checks found. Choose the checks folder below. '
                         'A person must review and approve checks before they can judge a change.')
    if checks.problems:
        help_text.append('Correct the listed file problems before verifying.')
    return {'folder': str(root), 'godot': found, 'routes': len(checks.routes),
            'checks': len(checks.specs), 'drafts': checks.drafts, 'problems': checks.problems,
            'help': ' '.join(help_text) or 'Project, routes and approved checks found.'}


class App:
    def __init__(self, store, start):
        self.store, self.start = store, start
        self.owned = set()
        self.lock = threading.RLock()
        self.waiters = []
        self.closing = False

    def own(self, job_id):
        with self.lock:
            if job_id not in self.owned:
                raise UnknownJob('No job from this app session has that address.')

    def create(self, body):
        doc = build(body)
        from harness.adapters import get

        for side in ('base', 'head'):
            root = Path(doc[side]['checkout'])
            if not root.is_dir() or not get('godot').is_project(root / doc['project']['game']):
                raise ValueError(f'Choose an existing Godot project for {"Before" if side == "base" else "After"}. '
                                 'Use Check folders for help. Nothing was run.')
        with self.lock:
            if self.closing:
                raise ValueError('The app is stopping. Nothing was run.')
            status, created = self.store.create(doc)
            job_id = status['id']
            self.owned.add(job_id)
            try:
                proc = self.start(self.store, job_id) if created else None
            except Exception:
                self.store.finish(job_id, 'failed', reasons=['The worker could not be started. No verdict.'])
                raise
            waiter = threading.Thread(target=runner.wait, args=(self.store, job_id, proc), daemon=True)
            waiter.start()
            self.waiters.append(waiter)
        return self.status(job_id)

    def status(self, job_id):
        self.own(job_id)
        doc = self.store.status(job_id)  # validates the record; unfinished/empty is never success
        phase = doc['phase']
        state = doc['decision'] if phase == 'completed' else phase if phase in FINAL else 'running'
        report = None
        if phase == 'completed' and doc['output']:
            try:
                self.report(job_id, ['index.html'])
                report = f'/reports/{job_id}/index.html'
            except (OSError, UnknownJob):
                pass
        return {key: doc[key] for key in ('id', 'phase', 'decision', 'history', 'reasons', 'diagnostics')} | {
            'state': state, 'report': report}

    def report(self, job_id, parts):
        self.own(job_id)
        doc = self.store.status(job_id)
        if doc['phase'] != 'completed' or not doc['output']:
            raise UnknownJob('This job has no finished report.')
        # Only the gate's existing page and its PNG copies. Walk with directory descriptors so a
        # link (even one swapped during the read) cannot turn a report request into a file server.
        if not (parts == ['index.html'] or len(parts) == 2 and parts[0] == 'assets'
                and parts[1].endswith('.png')) or any(p in ('', '.', '..') or '/' in p or '\\' in p for p in parts):
            raise UnknownJob('No such report file.')
        fd = os.open(self.store.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in ['jobs', job_id, 'output', 'review', *parts[:-1]]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(file_fd, 'rb') as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise UnknownJob('No such report file.')
                data = source.read(64 * 1024 * 1024 + 1)
                if len(data) > 64 * 1024 * 1024:
                    raise UnknownJob('Report file exceeds the local app size limit.')
                return data
        finally:
            os.close(fd)

    def close(self):
        with self.lock:
            self.closing = True
            for job_id in self.owned:
                if self.store.status(job_id)['phase'] not in FINAL:
                    self.store.cancel(job_id)
        for waiter in self.waiters:
            waiter.join(6)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_close(self):
        super().server_close()
        if hasattr(self, 'app'):
            self.app.close()


class Handler(BaseHTTPRequestHandler):
    server_version = 'Expectrail'

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        pass  # Never log the opening URL or its token.

    def reply(self, code, data, content_type='application/json; charset=utf-8', *, cookie=False, report=False):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        policy = ("sandbox allow-same-origin; default-src 'none'; script-src 'none'; "
                  "style-src 'unsafe-inline'; img-src 'self'; " if report else
                  f"default-src 'none'; script-src 'nonce-{self.server.nonce}'; "
                  f"style-src 'nonce-{self.server.nonce}'; connect-src 'self'; ")
        self.send_header('Content-Security-Policy', policy + "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        if cookie:
            self.send_header('Set-Cookie', f'{self.server.cookie}={self.server.token}; Path=/; HttpOnly; SameSite=Strict')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def problem(self, code, detail):
        self.reply(code, {'state': 'could-not-be-carried-out', 'detail': detail})

    def authorized(self, path, query):
        hosts = [f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}']
        host = self.headers.get_all('Host', [])
        if len(host) != 1 or host[0] not in hosts:
            self.problem(403, 'This address is not allowed. Use the address printed by Expectrail.')
            return False
        origins = self.headers.get_all('Origin', [])
        if origins and origins != ['http://' + host[0]]:
            self.problem(403, 'Requests from another page are not allowed.')
            return False
        values = self.headers.get_all('X-Expectrail-Token', [])
        # APIs always require the header, never a URL parameter or an ambient browser cookie.
        if not path.startswith('/api/') and not values:
            if path == '/' and 'token' in query:
                values = query['token']
            else:
                cookie = SimpleCookie()
                try:
                    cookie.load(self.headers.get('Cookie', ''))
                    if self.server.cookie in cookie:
                        values = [cookie[self.server.cookie].value]
                except CookieError:
                    pass
        if len(values) != 1 or not secrets.compare_digest(values[0].encode(), self.server.token.encode()):
            self.problem(401, 'Open the full address printed by Expectrail, including its token.')
            return False
        return True

    def body(self):
        sizes = self.headers.get_all('Content-Length', [])
        if self.headers.get('Transfer-Encoding') or len(sizes) != 1:
            raise ValueError('A single Content-Length is required.')
        size = int(sizes[0])
        if not 0 < size <= LIMIT:
            raise ValueError('Request body is missing or too large.')
        if self.headers.get_content_type() != 'application/json':
            raise ValueError('Send application/json.')
        doc = json.loads(self.rfile.read(size))
        if not isinstance(doc, dict):
            raise ValueError('Send a JSON object.')
        return doc

    def dispatch(self):
        try:
            url = urlsplit(self.path)
            path = unquote(url.path)
            query = parse_qs(url.query, max_num_fields=4)
            if not self.authorized(path, query):
                return
            if url.scheme or url.netloc:
                raise ValueError('Use a local path.')
            if self.command not in ('GET', 'POST'):
                return self.problem(405, 'Use POST for actions and GET to read.')
            app = self.server.app
            if path == '/':
                if self.command != 'GET':
                    return self.problem(405, 'Use GET to open the app.')
                page = app_page.PAGE.replace('__NONCE__', self.server.nonce).replace('__TOKEN__', self.server.token)
                return self.reply(200, page.encode(), 'text/html; charset=utf-8', cookie=True)
            if path in ('/api/inspect', '/api/jobs') or path.startswith('/api/jobs/') and path.endswith('/cancel'):
                if self.command != 'POST':
                    return self.problem(405, 'This action requires POST.')
                body = self.body()
                if path == '/api/inspect':
                    return self.reply(200, inspect_project(body))
                if path == '/api/jobs':
                    return self.reply(201, app.create(body))
                job_id = path.removeprefix('/api/jobs/').removesuffix('/cancel')
                app.own(job_id)
                app.store.cancel(job_id)
                return self.reply(200, app.status(job_id))
            if self.command != 'GET':
                return self.problem(405, 'Use GET to read.')
            if path.startswith('/api/jobs/'):
                return self.reply(200, app.status(path.removeprefix('/api/jobs/')))
            if path.startswith('/reports/'):
                job_id, *parts = path.removeprefix('/reports/').split('/')
                try:
                    data = app.report(job_id, parts)
                except OSError:
                    raise UnknownJob('No such report file.') from None
                return self.reply(200, data, 'text/html; charset=utf-8' if parts == ['index.html'] else 'image/png',
                                  report=True)
            raise UnknownJob('No such page.')
        except UnknownJob as exc:
            self.problem(404, str(exc))
        except (ValueError, OSError, StoreError) as exc:
            self.problem(400, str(exc))
        except Exception:
            self.problem(500, 'The app could not complete this request. No result is available here.')

    def __getattr__(self, name):
        # Authenticate unsupported HTTP methods too, before rejecting them.
        if name.startswith('do_'):
            return self.dispatch
        raise AttributeError(name)

    do_GET = do_POST = do_HEAD = do_OPTIONS = do_PUT = do_DELETE = do_PATCH = dispatch


def create_server(store=None, *, start=runner.spawn):
    server = Server(('127.0.0.1', 0), Handler)
    server.token = secrets.token_urlsafe(32)
    server.nonce = secrets.token_urlsafe(24)
    server.cookie = f'expectrail_{server.server_port}'
    server.app = App(store if store is not None else JobStore(Path.home() / '.local/share/expectrail/app-jobs'), start)
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(prog='expectrail app', description='Open Expectrail locally on 127.0.0.1.')
    parser.add_argument('--jobs-root', type=Path, help='Job storage outside both game folders.')
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 5  # 2 belongs to a verifier's needs-review decision
    try:
        server = create_server(JobStore(args.jobs_root) if args.jobs_root else None)
    except OSError as exc:
        print(f'Expectrail could not start: {exc}. No verification was run.', file=sys.stderr)
        return 5
    print(f'Open http://127.0.0.1:{server.server_port}/?token={server.token}', flush=True)
    print('Keep this process running. Press Ctrl+C to stop the app and cancel unfinished jobs.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
