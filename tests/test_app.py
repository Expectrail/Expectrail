"""The local app over loopback HTTP. Replays use public fixtures, never Godot."""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from expectrail.orchestrator import engines, request, runner
from expectrail.orchestrator.store import JobStore, diagnostic
from tests.test_ci_gate import FakeReplay, make_repo
from tests.test_orchestrator import STAND_INS

ROOT = Path(__file__).resolve().parent.parent


class CommandTest(unittest.TestCase):
    def test_app_command_help(self):
        done = subprocess.run([sys.executable, '-m', 'expectrail.cli', 'app', '--help'],
                              cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('127.0.0.1', done.stdout)


    def test_bad_app_option_is_usage_error_not_needs_review(self):
        done = subprocess.run([sys.executable, '-m', 'expectrail.cli', 'app', '--unknown'],
                              cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual((done.returncode, done.stdout), (5, ''))

    def test_bind_failure_is_reported_without_a_verdict(self):
        from expectrail import app
        with mock.patch.object(app, 'create_server', side_effect=OSError('cannot bind')):
            with mock.patch('sys.stderr') as error:
                self.assertEqual(app.main([]), 5)
        self.assertIn('could not start', ''.join(call.args[0] for call in error.write.call_args_list))


class HTTPTest(unittest.TestCase):
    def setUp(self):
        from expectrail import app
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.before = make_repo(self.root / 'before', bug=True)
        self.after = make_repo(self.root / 'after')
        self.store = JobStore(self.root / 'jobs')
        self.workers = []
        self.engine = engines.GodotGate(replay=FakeReplay(), rule='engine-only')
        self.starter = None
        self.server = app.create_server(self.store, start=self.start)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.port = self.server.server_port
        self.token = self.server.token
        self.body = {'before': str(self.before), 'after': str(self.after),
                     'game': 'game/platformer', 'routes': 'routes/*.json', 'specs': 'specs'}

    def start(self, store, job_id):
        if self.starter:
            return self.starter(store, job_id)
        thread = threading.Thread(target=runner.work, args=(store, job_id),
                                  kwargs={'engines': {'godot': self.engine}}, daemon=True)
        thread.start()
        self.workers.append(thread)

    def close(self):
        self.server.shutdown()
        self.thread.join(5)
        self.server.server_close()
        for worker in self.workers:
            worker.join(10)
            self.assertFalse(worker.is_alive())

    def http(self, method, path, body=None, *, token=True, headers=None):
        h = {'Host': f'127.0.0.1:{self.port}'}
        if token:
            h['X-Expectrail-Token'] = self.token if token is True else token
        if body is not None:
            body = json.dumps(body).encode()
            h['Content-Type'] = 'application/json'
        h.update(headers or {})
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        try:
            connection.request(method, path, body, h)
            response = connection.getresponse()
            data = response.read()
            got = dict(response.getheaders())
            self.assertFalse(any(key.lower().startswith('access-control-') for key in got), got)
            if got.get('Content-Type', '').startswith('application/json'):
                data = json.loads(data)
            return response.status, data, got
        finally:
            connection.close()

    def create(self, **changes):
        code, data, _ = self.http('POST', '/api/jobs', self.body | changes)
        self.assertEqual(code, 201, data)
        return data['id']

    def finished(self, job_id):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            code, data, _ = self.http('GET', '/api/jobs/' + job_id)
            self.assertEqual(code, 200, data)
            if data['state'] != 'running':
                return data
            time.sleep(.02)
        self.fail('job did not finish')

    def test_initial_page_removes_url_token_and_apis_use_header(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        code, page, headers = self.http('GET', '/?token=' + self.token, token=False)
        self.assertEqual(code, 200)
        for text in (b'sessionStorage', b'history.replaceState', b'X-Expectrail-Token',
                     b'Evidence viewer', b'viewport', b'@media'):
            self.assertIn(text, page)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.http('GET', '/', token=False, headers={'Cookie': cookie})[0], 200)
        for path in ('/api/jobs/unknown?token=' + self.token, '/api/jobs/unknown'):
            self.assertEqual(self.http('GET', path, token=False, headers={'Cookie': cookie})[0], 401)
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])

    def test_every_route_needs_token_and_no_cors_is_sent(self):
        for method, path in (('GET', '/'), ('POST', '/api/inspect'), ('POST', '/api/jobs'),
                             ('GET', '/api/jobs/unknown'), ('POST', '/api/jobs/unknown/cancel'),
                             ('GET', '/reports/unknown/index.html'), ('OPTIONS', '/api/jobs'), ('TRACE', '/')):
            for token in (False, 'wrong'):
                with self.subTest(method=method, path=path, token=token):
                    self.assertEqual(self.http(method, path, token=token)[0], 401)
        self.assertEqual(self.http('OPTIONS', '/api/jobs')[0], 405)

    def test_host_and_origin_are_checked_before_actions(self):
        for host in ('evil.example', f'evil.example:{self.port}', '127.0.0.1', 'localhost:1',
                     f'127.0.0.1:{self.port}.evil.example', ''):
            self.assertEqual(self.http('POST', '/api/jobs', self.body, headers={'Host': host})[0], 403)
        self.assertEqual(self.http('GET', '/', headers={'Host': f'localhost:{self.port}'})[0], 200)
        self.assertEqual(self.http('POST', '/api/jobs', self.body,
                                  headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertFalse(list((self.store.root / 'jobs').glob('*')))
        connection = http.client.HTTPConnection('127.0.0.1', self.port)
        connection.putrequest('GET', '/', skip_host=True)
        connection.putheader('Host', f'127.0.0.1:{self.port}')
        connection.putheader('Host', 'evil.example')
        connection.putheader('X-Expectrail-Token', self.token)
        connection.endheaders()
        self.assertEqual(connection.getresponse().status, 403)
        connection.close()

    def test_actions_require_post(self):
        for path in ('/api/inspect', '/api/jobs', '/api/jobs/unknown/cancel'):
            self.assertEqual(self.http('GET', path)[0], 405)
        self.assertEqual(self.http('PUT', '/api/jobs', self.body)[0], 405)
        self.assertFalse(list((self.store.root / 'jobs').glob('*')))

    def test_inspection_uses_existing_check_reader(self):
        code, found, _ = self.http('POST', '/api/inspect', self.body | {'folder': str(self.before)})
        self.assertEqual(code, 200, found)
        self.assertTrue(found['godot'])
        self.assertEqual((found['routes'], found['checks']), (2, 1))
        self.assertEqual(found['problems'], [])
        (self.before / 'specs' / 'player-stays-above-ground.json').unlink()
        for path in (self.before / 'routes').glob('*.json'):
            path.unlink()
        _, found, _ = self.http('POST', '/api/inspect', self.body | {'folder': str(self.before)})
        self.assertEqual((found['routes'], found['checks']), (0, 0))
        self.assertTrue(found['problems'])
        self.assertIn('routes', found['help'])
        self.assertIn('checks', found['help'])

    def test_missing_folder_and_non_godot_folder_are_explained(self):
        ordinary = self.root / 'ordinary'
        ordinary.mkdir()
        for folder in (self.root / 'missing', ordinary):
            with self.subTest(folder=folder):
                code, found, _ = self.http('POST', '/api/inspect', self.body | {'folder': str(folder)})
                self.assertEqual(code, 200)
                self.assertFalse(found['godot'])
                self.assertTrue(found['help'])
                code, result, _ = self.http('POST', '/api/jobs', self.body | {'after': str(folder)})
                self.assertEqual(code, 400)
                self.assertEqual(result['state'], 'could-not-be-carried-out')

    def test_verdicts_and_existing_report_from_fake_replays(self):
        for expected in ('accept', 'reject', 'needs-review'):
            with self.subTest(expected=expected):
                game = self.after / 'game/platformer'
                if expected == 'reject':
                    (game / 'BUG').write_text('1')
                if expected == 'needs-review':
                    (game / 'CRASH').write_text('1')
                job_id = self.create()
                result = self.finished(job_id)
                self.assertEqual(result['state'], expected, result)
                self.assertEqual(result['decision'], expected)
                phases = [entry['phase'] for entry in result['history']]
                self.assertIn('executing', phases)
                self.assertIn('evaluating', phases)
                saved = self.store.request(job_id)
                self.assertEqual(saved, request.build(adapter='godot', head=self.after, base=self.before,
                                  game='game/platformer', routes=['routes/*.json'], specs='specs'))
                code, page, headers = self.http('GET', result['report'])
                self.assertEqual(code, 200, page)
                self.assertIn(b'<!doctype html>', page.lower())
                self.assertIn("script-src 'none'", headers['Content-Security-Policy'])

    def test_stand_in_and_empty_or_failed_workers(self):
        self.engine = STAND_INS['instant']
        result = self.finished(self.create())
        self.assertEqual(result['state'], 'accept')
        self.assertIsNone(result['report'])  # the stand-in wrote evidence, not a review page
        for engine in (Empty(), Broken()):
            self.engine = engine
            result = self.finished(self.create())
            self.assertEqual(result['state'], 'failed', result)
            self.assertIsNone(result['decision'])
            self.assertIsNone(result['report'])

    def test_missing_tools_needs_review_without_a_report(self):
        self.engine = engines.GodotGate(replay=FakeReplay(), rule='engine-only')
        with mock.patch.object(self.engine, 'preflight', return_value=[
                diagnostic('TOOL_MISSING', stage='preparing', detail='Install the missing engine.')]):
            result = self.finished(self.create())
        self.assertEqual(result['state'], 'needs-review', result)
        self.assertIsNone(result['report'])
        self.assertIn('Install the missing engine.', str(result['diagnostics']))

    def test_running_then_cancel_stops_real_worker_and_child(self):
        def start(store, job_id):
            code = ('from pathlib import Path; from expectrail.orchestrator import runner; '
                    'from expectrail.orchestrator.store import JobStore, diagnostic; '
                    'from tests.test_orchestrator import STAND_INS; '
                    'import sys; runner.work(JobStore(Path(sys.argv[1])), sys.argv[2], '
                    'engines={"godot": STAND_INS["slow"]}, own_group=True)')
            proc = runner.spawn(store, job_id, command=[sys.executable, '-c', code, str(store.root), job_id])
            self.addCleanup(lambda: proc.poll() is None and proc.kill())
            return proc
        self.starter = start
        job_id = self.create()
        child_file = self.store.paths(job_id).work / 'child.pid'
        deadline = time.monotonic() + 10
        while not child_file.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(child_file.exists())
        result = self.http('GET', '/api/jobs/' + job_id)[1]
        self.assertEqual(result['state'], 'running')
        self.assertIsNone(result['decision'])
        self.assertIsNone(result['report'])
        result = self.http('POST', '/api/jobs/' + job_id + '/cancel', {})[1]
        self.assertEqual(result['state'], 'cancelled', result)
        self.assertIsNone(result['decision'])
        from expectrail.orchestrator.store import alive
        child = int(child_file.read_text())
        deadline = time.monotonic() + 5
        while alive(child) and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertFalse(alive(child))
        self.assertEqual(self.finished(job_id)['state'], 'cancelled')

    def test_queued_job_and_cancelled_job_never_expose_staging(self):
        self.starter = lambda store, job_id: None
        job_id = self.create()
        paths = self.store.paths(job_id)
        paths.staging.mkdir()
        (paths.staging / 'index.html').write_text('unfinished')
        state = self.http('GET', '/api/jobs/' + job_id)[1]
        self.assertEqual((state['phase'], state['state'], state['decision'], state['report']),
                         ('queued', 'running', None, None))
        self.assertEqual(self.http('GET', f'/reports/{job_id}/index.html')[0], 404)
        self.assertEqual(self.http('POST', f'/api/jobs/{job_id}/cancel', {})[1]['state'], 'cancelled')
        self.assertEqual(self.http('GET', f'/reports/{job_id}/index.html')[0], 404)

    def test_dead_worker_becomes_failed_and_late_cancel_keeps_a_verdict(self):
        self.starter = lambda store, job_id: runner.spawn(store, job_id, command=[sys.executable, '-c', 'pass'])
        self.assertEqual(self.finished(self.create())['state'], 'failed')
        self.starter = None
        job_id = self.create()
        self.assertEqual(self.finished(job_id)['state'], 'accept')
        self.assertEqual(self.http('POST', f'/api/jobs/{job_id}/cancel', {})[1]['state'], 'accept')

    def test_malformed_requests_are_not_jobs(self):
        for raw, headers in ((b'{', {}), (b'[]', {}), (b'{}', {'Content-Type': 'text/plain'}),
                             (b'{}', {'Content-Length': str(65537)})):
            connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
            try:
                connection.request('POST', '/api/jobs', raw,
                    {'X-Expectrail-Token': self.token, 'Content-Type': 'application/json'} | headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 400)
                self.assertEqual(json.loads(response.read())['state'], 'could-not-be-carried-out')
            finally:
                connection.close()
        self.assertFalse(list((self.store.root / 'jobs').glob('*')))

    def test_bad_input_or_spawn_error_cannot_be_success(self):
        for change in ({'before': ''}, {'game': '../outside'}, {'routes': ''}, {'specs': '/tmp'},
                       {'after': None}, {'routes': ['routes/*.json']}):
            code, result, _ = self.http('POST', '/api/jobs', self.body | change)
            self.assertEqual(code, 400, result)
            self.assertEqual(result['state'], 'could-not-be-carried-out')
        self.starter = mock.Mock(side_effect=OSError('worker unavailable'))
        code, result, _ = self.http('POST', '/api/jobs', self.body)
        self.assertEqual(code, 400)
        self.assertEqual(result['state'], 'could-not-be-carried-out')
        job_id = self.starter.call_args.args[1]
        self.assertEqual(self.store.status(job_id)['phase'], 'failed')

    def test_only_owned_jobs_and_report_files_are_served(self):
        other, _ = self.store.create(request.build(adapter='godot', head=self.after, base=self.before,
                    game='game/platformer', routes=['routes/*.json'], specs='specs'))
        for method, path in (('GET', '/api/jobs/' + other['id']),
                             ('POST', '/api/jobs/' + other['id'] + '/cancel')):
            self.assertEqual(self.http(method, path, {} if method == 'POST' else None)[0], 404)
        (self.after / 'game/platformer/BUG').write_text('1')
        job_id = self.create()
        result = self.finished(job_id)
        report = result['report']
        _, _, headers = self.http('GET', '/?token=' + self.token, token=False)
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.http('GET', report, token=False, headers={'Cookie': cookie})[0], 200)
        review = self.store.paths(job_id).output / 'review'
        asset = next((review / 'assets').glob('*.png'))
        self.assertEqual(self.http('GET', f'/reports/{job_id}/assets/{asset.name}',
                                  token=False, headers={'Cookie': cookie})[1], asset.read_bytes())
        secret = self.root / 'private.txt'
        secret.write_text('must not be served')
        (review / 'assets/leak.png').symlink_to(secret)
        (review / 'escape').symlink_to(self.root, target_is_directory=True)
        for path in ('/etc/passwd', '/app.py', f'/reports/{other["id"]}/index.html',
                     f'/reports/{job_id}/../request.json', f'/reports/{job_id}/%2e%2e/request.json',
                     f'/reports/{job_id}/%252e%252e/request.json', f'/reports/{job_id}/assets/leak.png',
                     f'/reports/{job_id}/escape/private.txt', f'/reports/{job_id}/../../private.txt',
                     f'/reports/{job_id}/findings.json'):
            with self.subTest(path=path):
                code, data, _ = self.http('GET', path)
                self.assertEqual(code, 404, data)
                self.assertNotIn(b'must not be served', data if isinstance(data, bytes) else str(data).encode())


class Empty:
    def preflight(self, doc):
        return []

    def execute(self, doc, paths, advance):
        return engines.Result('accept')


class Broken(Empty):
    def execute(self, doc, paths, advance):
        raise RuntimeError('stand-in failure')


if __name__ == '__main__':
    unittest.main()
