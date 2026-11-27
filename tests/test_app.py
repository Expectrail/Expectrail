"""The local app over loopback HTTP. Replays use public fixtures, never Godot."""
from __future__ import annotations

from contextlib import redirect_stdout
import http.client
import io
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


class ObserverWordsTest(unittest.TestCase):
    def test_empty_public_check_results_do_not_credit_configured_observers(self):
        from expectrail.app import judged_by

        for observers in (
            {'rule': 'both', 'visual': {'provider': 'recorded: clean, fall-through-bug'}},
            {'rule': 'both', 'visual': {'provider': 'test-model'}},
            {'rule': 'engine-only'},
        ):
            with self.subTest(observers=observers):
                status = {'phase': 'completed', 'decision': 'needs-review', 'observers': observers}
                self.assertEqual(judged_by(status, {'checks': []}),
                                 'This run has no results from approved public checks.')

    def test_nonapplicable_public_checks_do_not_credit_observers(self):
        from expectrail.app import judged_by

        for before in (None, 'not-applicable'):
            skipped = {'before': before, 'after': 'not-applicable'}
            for observers in (
                {'rule': 'both', 'visual': {'provider': 'recorded: sample'}},
                {'rule': 'both', 'visual': {'provider': 'test-model'}},
                {'rule': 'engine-only'},
            ):
                with self.subTest(before=before, observers=observers):
                    status = {'phase': 'completed', 'decision': 'needs-review', 'observers': observers}
                    self.assertEqual(judged_by(status, {'checks': [skipped]}),
                                     'None of the approved public checks applied to the selected routes.')

    def test_a_route_outside_the_scope_does_not_hide_a_checked_route(self):
        from expectrail.app import judged_by

        status = {'phase': 'completed', 'decision': 'accept',
                  'observers': {'rule': 'both', 'visual': {'provider': 'recorded: sample'}}}
        checks = [{'before': 'not-applicable', 'after': 'not-applicable'},
                  {'before': 'pass', 'after': 'pass'}]
        self.assertIn('looked up vision answers in the recording', judged_by(status, {'checks': checks}))


class HTTPTest(unittest.TestCase):
    def setUp(self):
        from expectrail import app
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()  # the app records resolved folders (#378)
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

    def test_verify_command_and_app_decide_the_same_change(self):
        from expectrail import cli
        from tests.test_two_observers import Game

        candidate = self.after / 'game/platformer'
        cli_store = JobStore(self.root / 'cli-jobs')

        def start_cli_worker(store, job_id):
            # The real spawn sends worker output to this log. Keep the CLI's JSON stream separate.
            with store.paths(job_id).log.open('a') as log, redirect_stdout(log):
                runner.work(store, job_id, engines={'godot': self.engine})

        for decision, marker, exit_code in [('accept', None, 0), ('reject', 'BUG', 1),
                                            ('needs-review', 'CRASH', 2)]:
            with self.subTest(decision=decision):
                if decision == 'reject':
                    (self.before / 'game/platformer/BUG').unlink()
                if marker:
                    (candidate / marker).touch()
                game = Game()
                self.engine = engines.GodotGate(replay=game.replay, visual=game.observer(), rule='both')
                shown = self.finished(self.create())
                command = ['verify', '--jobs-root', str(cli_store.root), '--base', str(self.before),
                           '--head', str(self.after), '--game', self.body['game'], '--routes', self.body['routes'],
                           '--specs', self.body['specs'], '--json']
                with mock.patch.object(runner, 'spawn', start_cli_worker), redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(cli.main(command), exit_code)
                printed = json.loads(output.getvalue())
                self.assertEqual(self.store.request(shown['id']), cli_store.request(printed['id']))
                self.assertEqual(self.store.status(shown['id'])['inputs'], printed['inputs'])
                self.assertNotEqual(printed['inputs']['baseTree'], printed['inputs']['headTree'])
                self.assertEqual((shown['state'], shown['decision'], printed['decision']), (decision,) * 3)
                if marker:
                    (candidate / marker).unlink()

    def test_removed_project_preset_is_refused_without_starting_a_job(self):
        body = {'preset': 'kinematic-character', 'before': str(self.before / 'game/platformer'),
                'after': str(self.after / 'game/platformer')}
        code, error, _ = self.http('POST', '/api/jobs', body)
        self.assertEqual(code, 400)
        self.assertIn('config', error['detail'])
        self.assertFalse(list((self.store.root / 'jobs').glob('*')))

    def test_configured_project_supplies_only_its_selected_policy_to_the_normal_worker(self):
        from tests.test_app_projects import configured_project
        import shutil

        before = configured_project(self.root / 'configured-before')
        after = self.root / 'configured-after'
        shutil.copytree(before, after)
        body = {'projectConfig': True, 'before': str(before), 'after': str(after)}
        checked = self.http('POST', '/api/inspect', body | {'folder': str(before)})[1]
        self.assertEqual((checked['godot'], checked['routes'], checked['checks']), (True, 1, 1))
        self.assertFalse((before / 'specs').exists())
        with mock.patch.object(self.server.app, 'start', return_value=None) as normal_start:
            job_id = self.create(**body)
            normal_start.assert_called_once_with(self.store, job_id)
        self.store.cancel(job_id)
        doc = self.store.request(job_id)
        for arm, source in [('base', before), ('head', after)]:
            checkout = Path(doc[arm]['checkout'])
            self.assertEqual((checkout / 'routes/000.json').read_bytes(), (source / 'inputs/first.json').read_bytes())
            self.assertEqual((checkout / 'specs/000.json').read_bytes(), (source / 'checks/nested/floor.json').read_bytes())
            self.assertEqual(request.tree_digest(checkout / 'project'), request.tree_digest(source))
            self.assertFalse((source / 'specs').exists())

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

    def test_reject_without_repair_names_the_form_controls_in_results_and_history(self):
        (self.after / 'game/platformer/BUG').touch()
        job_id = self.create()
        result = self.finished(job_id)
        self.assertEqual(result['decision'], 'reject')
        page = self.http('GET', '/')[1].decode()
        checkbox = 'Try to fix the game if verification rejects it'
        cap = 'Maximum fixer spend in US dollars'
        for label in (checkbox, cap):
            self.assertIn(label, page)
            self.assertIn(label, result['summary'])
        self.assertNotIn('--auto-fix', result['summary'])
        self.assertNotIn('autoFix', self.store.request(job_id))
        self.server.app.owned.clear()
        past, = self.http('GET', '/api/history')[1]['jobs']
        self.assertEqual((past['id'], past['summary']), (job_id, result['summary']))

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


    def test_viewer_owned_finished_files_and_security(self):
        from expectrail import viewer
        import base64
        import hashlib
        (self.after / 'game/platformer/BUG').write_text('1')
        job_id = self.create()
        result = self.finished(job_id)
        url = result['viewer']
        code, page, headers = self.http('GET', url)
        self.assertEqual(code, 200)
        self.assertIn(b'Expectrail evidence viewer', page)
        digest = base64.b64encode(hashlib.sha256(viewer.SCRIPT.encode()).digest()).decode()
        self.assertIn("script-src 'sha256-" + digest + "'", headers['Content-Security-Policy'])
        self.assertNotIn("script-src 'unsafe-inline'", headers['Content-Security-Policy'])
        self.assertNotIn("script-src 'self'", headers['Content-Security-Policy'])
        folder = self.store.paths(job_id).output / 'viewer'
        # The session supplies the job's auto-fix section after the gate wrote its frame viewer.
        expected = (folder / 'index.html').read_bytes().replace(b'<section id="auto-fix"></section>',
                                                               viewer.auto_fix_section({}).encode(), 1)
        self.assertEqual(page, expected)
        self.assertIn(b'Auto-fix is off; turn it on with --auto-fix', page)
        frame = next((folder / 'frames').glob('*.png'))
        prefix = f'/viewers/{job_id}/'
        _, _, opening = self.http('GET', '/?token=' + self.token, token=False)
        cookie = {'Cookie': opening['Set-Cookie'].split(';')[0]}
        self.assertEqual(self.http('GET', prefix + 'frames/' + frame.name, token=False,
                                  headers=cookie)[1], frame.read_bytes())
        self.assertEqual(self.http('GET', prefix + viewer.EXPORT_NAME)[0], 200)
        other, _ = self.store.create(self.store.request(job_id))
        leak = folder / 'frames/after-leak-00000000.png'
        leak.symlink_to(self.root / 'private.txt')
        (self.root / 'private.txt').write_text('private marker')
        for path in (f'/viewers/{other["id"]}/index.html', prefix + 'frames/' + leak.name,
                     prefix + '../request.json', prefix + '%2e%2e/request.json',
                     prefix + '%252e%252e/request.json', prefix + 'frames/../../request.json',
                     prefix + 'views.json', prefix + 'extra.js', prefix + 'frames/x.png'):
            with self.subTest(path=path):
                self.assertEqual(self.http('GET', path)[0], 404)
        for name in ('index.html', viewer.EXPORT_NAME):
            target = folder / name
            saved = target.read_bytes()
            target.unlink()
            target.symlink_to(self.root / 'private.txt')
            self.assertEqual(self.http('GET', prefix + name)[0], 404)
            target.unlink()
            target.write_bytes(saved)
        frames = folder / 'frames'
        frames.rename(folder / 'saved-frames')
        frames.symlink_to(folder / 'saved-frames', target_is_directory=True)
        self.assertEqual(self.http('GET', prefix + 'frames/' + frame.name)[0], 404)
        frames.unlink()
        (folder / 'saved-frames').rename(frames)
        folder.rename(folder.with_name('saved-viewer'))
        folder.symlink_to(folder.with_name('saved-viewer'), target_is_directory=True)
        self.assertEqual(self.http('GET', url)[0], 404)

    def test_page_connects_history_and_record_wording(self):
        page = self.http('GET', '/')[1].decode()
        for text in ('/api/history', 'Past runs', 'Open run', 'data.judgedBy', 'data.viewer', 'row.createdAt',
                     'row.before', 'row.after', 'row.summary', 'row.sessionOwned'):
            self.assertIn(text, page)
        self.assertNotIn('This is a diagnostic run using', page)
        self.assertNotIn('It is not included in this slice', page)

    def test_history_and_viewer_require_token_host_and_read_methods(self):
        for path in ('/api/history', '/viewers/unknown/index.html'):
            for token in (False, 'bad'):
                self.assertEqual(self.http('GET', path, token=token)[0], 401)
            self.assertEqual(self.http('GET', path, headers={'Host': 'evil.example'})[0], 403)
            self.assertEqual(self.http('POST', path, {})[0], 405)
        _, _, opening = self.http('GET', '/?token=' + self.token, token=False)
        self.assertEqual(self.http('GET', '/api/history?token=' + self.token, token=False,
                        headers={'Cookie': opening['Set-Cookie'].split(';')[0]})[0], 401)

    def test_history_orders_all_jobs_and_never_upgrades_their_states(self):
        ids, states = [], []
        for expected in ('accept', 'reject', 'needs-review', 'failed'):
            if expected == 'reject':
                (self.after / 'game/platformer/BUG').write_text('1')
            if expected == 'needs-review':
                (self.after / 'game/platformer/CRASH').write_text('1')
            if expected == 'failed':
                self.engine = Broken()
            job_id = self.create()
            self.assertEqual(self.finished(job_id)['state'], expected)
            ids.append(job_id)
            states.append(expected)
        self.starter = lambda store, job_id: None
        for state in ('cancelled', 'running'):
            job_id = self.create()
            if state == 'cancelled':
                self.http('POST', f'/api/jobs/{job_id}/cancel', {})
            ids.append(job_id)
            states.append(state)
        code, data, _ = self.http('GET', '/api/history')
        self.assertEqual(code, 200)
        self.assertEqual([row['id'] for row in data['jobs']], ids[::-1])
        self.assertEqual([row['state'] for row in data['jobs']], states[::-1])
        for row in data['jobs']:
            self.assertEqual((row['before'], row['after']), (str(self.before), str(self.after)))
            self.assertEqual(row['createdAt'], self.store.status(row['id'])['createdAt'])
            self.assertTrue(row['summary'])
            if row['state'] in ('running', 'cancelled', 'failed'):
                self.assertNotIn('accepted', row['summary'].lower())
                self.assertIsNone(row['decision'])
            if row['state'] == 'running':
                self.assertIsNone(row['viewer'])
                self.assertEqual(self.http('GET', f'/viewers/{row["id"]}/index.html')[0], 404)
            else:
                self.assertEqual(self.http('GET', row['viewer'])[0], 200)
        # Simulate a new app session: metadata remains, artifact access does not transfer.
        self.server.app.owned.clear()
        rows = self.http('GET', '/api/history')[1]['jobs']
        self.assertEqual([row['id'] for row in rows], ids[::-1])
        self.assertTrue(all(row['viewer'] is None and row['report'] is None for row in rows))
        self.assertEqual(self.http('GET', '/viewers/' + ids[0] + '/index.html')[0], 404)
        self.store.cancel(ids[-1])

    def test_observer_words_follow_findings_and_missing_observers_are_diagnostic(self):
        result = self.finished(self.create())
        self.assertIn("Only the engine's record judged", result['judgedBy'])
        self.assertIn('an accept needs the vision model too', result['judgedBy'])
        self.assertIn('diagnostic', result['judgedBy'])
        from tests.test_two_observers import Game
        game = Game()
        self.engine = engines.GodotGate(replay=game.replay, rule='both', visual=game.observer())
        result = self.finished(self.create())
        self.assertEqual(result['state'], 'accept', result)
        self.assertIn("engine's record and the vision model judged every check", result['judgedBy'])
        self.engine = engines.GodotGate(replay=FakeReplay(), rule='both')
        result = self.finished(self.create())
        self.assertEqual(result['state'], 'needs-review')
        self.assertIn('vision model was not available', result['judgedBy'])
        self.assertNotIn('judged every check', result['judgedBy'])

    def test_status_observer_block_and_missing_settings_words(self):
        job_id = self.create()
        self.finished(job_id)
        original = self.store.status
        for block in ({'rule': 'engine-only'}, {'rule': 'both', 'visual': {'name': 'test'}}):
            with mock.patch.object(self.store, 'status', side_effect=lambda key: original(key) | {'observers': block}):
                result = self.http('GET', '/api/jobs/' + job_id)[1]
            self.assertIn('diagnostic' if block['rule'] == 'engine-only' else 'judged every check', result['judgedBy'])
        for name in ('MODEL_API_KEY', 'EXPECTRAIL_SAM_USD_CAP'):
            self.engine = engines.GodotGate(replay=FakeReplay(), rule='both')
            with mock.patch.object(self.engine, 'preflight', return_value=[
                    diagnostic('TOOL_MISSING', stage='preparing', detail=f'Missing {name}')]):
                result = self.finished(self.create())
            self.assertEqual(result['state'], 'needs-review')
            self.assertIn(name, result['judgedBy'])
            self.assertIn('before starting the app', result['judgedBy'])
            self.assertIn('secret key' if name == 'MODEL_API_KEY' else 'US dollars', result['judgedBy'])

    def test_replay_errors_are_reported_for_the_affected_versions_in_past_runs(self):
        from tests.test_two_observers import Game

        game = Game()
        def replay(route, project, out, frames):
            if (project / 'CRASH').exists():
                raise RuntimeError('stand-in replay stopped')
            return game.replay(route, project, out, frames)

        self.engine = engines.GodotGate(replay=replay, rule='both', visual=game.observer())
        (self.before / 'game/platformer/CRASH').touch()
        partial = self.finished(self.create())
        (self.after / 'game/platformer/CRASH').touch()
        stopped = self.finished(self.create())

        for result, message in (
                (partial, 'Some replays did not finish'),
                (stopped, 'None of the replays for these checks finished')):
            with self.subTest(job=result['id']):
                self.assertIn(message, result['judgedBy'])
                self.assertNotIn('judged every check', result['judgedBy'])
        self.assertEqual(stopped['decision'], 'needs-review')
        self.server.app.owned.clear()
        history = self.http('GET', '/api/history')[1]['jobs']
        self.assertEqual({row['id']: row['judgedBy'] for row in history},
                         {row['id']: row['judgedBy'] for row in (partial, stopped)})

    def test_reopened_sample_identifies_recorded_vision_only_when_replays_finished(self):
        from expectrail.cli import _sample_observer
        from tests.test_two_observers import Game

        bank = _sample_observer()
        self.engine = engines.GodotGate(replay=Game().replay, rule='both', visual=bank)
        completed = self.finished(self.create())
        stopped_replay = mock.Mock(side_effect=RuntimeError('stand-in replay stopped'))
        self.engine = engines.GodotGate(replay=stopped_replay, rule='both', visual=bank)
        stopped = self.finished(self.create())

        self.server.app.owned.clear()
        history = {row['id']: row for row in self.http('GET', '/api/history')[1]['jobs']}
        for result in (completed, history[completed['id']]):
            self.assertIn('looked up vision answers in the recording', result['judgedBy'])
            self.assertIn('No live model was called', result['judgedBy'])
        for result in (stopped, history[stopped['id']]):
            self.assertIn('None of the replays for these checks finished', result['judgedBy'])
            self.assertNotIn('looked up vision answers', result['judgedBy'])


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
