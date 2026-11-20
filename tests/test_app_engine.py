"""App and CLI use the real Godot worker on public inputs, with vision settings absent."""
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from expectrail import app
from expectrail.gate import record
from expectrail.orchestrator import sample
from expectrail.orchestrator.store import JobStore
from tests.test_second_project import checkout
from tests.tool_requirements import godot_binary, require_tool

ROOT = Path(__file__).resolve().parent.parent


class AppEngineTest(unittest.TestCase):
    def setUp(self):
        binary = godot_binary()
        require_tool('xvfb-run')
        temp = tempfile.TemporaryDirectory(prefix='expectrail-app-engine-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        environment = {k: v for k, v in os.environ.items()
                       if k not in ('MODEL_API_KEY', 'EXPECTRAIL_SAM_USD_CAP') and
                       not k.startswith('EXPECTRAIL_VLM_')}
        environment['EXPECTRAIL_GODOT'] = str(binary)
        patch = mock.patch.dict(os.environ, environment, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.store = JobStore(self.root / 'app-jobs')
        self.server = app.create_server(self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def api(self, path, body=None, *, expected=200):
        headers = {'X-Expectrail-Token': self.server.token}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=20)
        try:
            connection.request('GET' if body is None else 'POST', path,
                               None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            raw = response.read()
            self.assertEqual(response.status, expected, raw[:600])
            return json.loads(raw) if response.headers['Content-Type'].startswith('application/json') else raw
        finally:
            connection.close()

    def completed(self, job_id):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            result = self.api('/api/jobs/' + job_id)
            if result['state'] != 'running':
                self.assertEqual(result['phase'], 'completed', result)
                return result
            time.sleep(0.5)
        self.fail('App job did not complete in five minutes')

    def findings(self, job_id):
        findings = record.read_record(self.store.paths(job_id).output / 'findings.json')
        self.assertIsNone(findings['observers']['visual'])
        self.assertGreater(findings['isolation']['replays'], 0)
        return findings

    def test_bundled_bug_and_fix_match_the_cli_with_real_replays(self):
        clean = sample.checkout(self.root / 'clean', bug=False)
        bug = sample.checkout(self.root / 'bug', bug=True)
        jobs = self.root / 'cli-jobs'
        for before, after, expected, exit_code in [(clean, bug, 'reject', 1), (bug, clean, 'needs-review', 2)]:
            with self.subTest(expected=expected):
                body = dict(before=str(before), after=str(after), game=sample.GAME,
                            routes=sample.ROUTE, specs=sample.SPECS)
                started = self.api('/api/jobs', body, expected=201)
                shown = self.completed(started['id'])
                cmd = [sys.executable, '-m', 'expectrail.cli', 'verify', '--jobs-root', str(jobs),
                       '--base', body['before'], '--head', body['after'], '--game', body['game'],
                       '--routes', body['routes'], '--specs', body['specs'], '--json']
                done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
                self.assertEqual(done.returncode, exit_code, done.stdout + done.stderr)
                printed = json.loads(done.stdout)
                self.assertEqual(shown['decision'], expected)
                self.assertEqual(printed['decision'], expected)
                saved = self.store.status(shown['id'])
                self.assertEqual(saved['inputs'], printed['inputs'])
                engine = 'fail' if expected == 'reject' else 'pass'
                findings = self.findings(shown['id'])
                self.assertEqual([c['observed']['after']['engine'] for c in findings['checks']], [engine])
                cli_findings = record.read_record(JobStore(jobs).paths(printed['id']).output / 'findings.json')
                self.assertEqual(cli_findings['checks'], findings['checks'])
                print(json.dumps(dict(case='bundled ' + ('bug' if exit_code == 1 else 'fix'),
                                      appJob=shown['id'], cliJob=printed['id'], cliExit=done.returncode,
                                      decision=expected, engine=engine, inputs=saved['inputs'])), flush=True)

    def test_outside_crate_run_in_the_browser(self):
        chromium = shutil.which('chromium') or shutil.which('chromium-browser')
        if not chromium:
            self.skipTest('Chromium is not installed')
        try:
            from playwright.sync_api import expect, sync_playwright
        except ModuleNotFoundError as exc:
            if exc.name != 'playwright':
                raise
            self.skipTest('Playwright is not installed')

        before = checkout(self.root / 'crate-before')
        after = checkout(self.root / 'crate-after', broken=True)
        origin = f'http://127.0.0.1:{self.server.server_port}'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=chromium, headless=True,
                                                  args=['--no-sandbox'])
            page = browser.new_page()
            page.route('**/*', lambda route: route.continue_()
                       if route.request.url.startswith(origin + '/') else route.abort())
            page.goto(origin + '/?token=' + self.server.token)
            page.locator('#paths summary').click()
            page.locator('#manual').check()
            for field, value in dict(before=str(before), after=str(after), game='project',
                                     routes='routes/walk.json', specs='specs').items():
                page.locator('#' + field).fill(value)
            page.get_by_role('button', name='Check folders').click()
            expect(page.locator('#inspection')).to_contain_text('1 usable routes; 1 approved checks')
            with page.expect_response(lambda response: response.url.endswith('/api/jobs') and
                                      response.request.method == 'POST') as submitted:
                page.get_by_role('button', name='Verify', exact=True).click()
            job_id = submitted.value.json()['id']
            expect(page.locator('#result-text')).to_contain_text('Reject', timeout=300_000)
            with page.expect_popup() as opened:
                page.locator('#viewer').click()
            viewer = opened.value
            viewer.wait_for_load_state()
            self.assertIn(job_id, viewer.url)
            expect(viewer.locator('body')).to_contain_text('Reject')
            browser.close()

        status = self.store.status(job_id)
        findings = self.findings(job_id)
        self.assertEqual(status['decision'], 'reject')
        self.assertEqual(findings['decision'], 'reject')
        check, = findings['checks']
        self.assertEqual(check['route'], 'walk')
        self.assertEqual(check['observed']['after']['engine'], 'fail')
        print(json.dumps(dict(project='Crate Run', appJob=job_id, decision=status['decision'],
                              isolation=findings['isolation'], check=check, inputs=status['inputs'])), flush=True)
