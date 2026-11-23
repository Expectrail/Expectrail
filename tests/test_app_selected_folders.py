"""Configured project selections in the current result and local history (#705)."""
import json
from pathlib import Path
import shutil
import subprocess
import threading
import unittest
from unittest import mock

from expectrail import app, project_job, viewer
from tests import test_app, test_app_projects


class SelectedFoldersTest(unittest.TestCase):
    def setUp(self):
        fixture = self.fixture = test_app.HTTPTest()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        self.before = test_app_projects.configured_project(fixture.root / 'My game before')
        self.after = fixture.root / 'My game after'
        shutil.copytree(self.before, self.after)

    def submit(self):
        code, job, _ = self.fixture.http('POST', '/api/jobs', {
            'before': str(self.before / 'project.godot'), 'after': str(self.after),
        })
        self.assertEqual(code, 201, job)
        return self.fixture.finished(job['id'])

    def test_result_and_reopened_history_identify_sources_while_worker_uses_snapshots(self):
        job = self.submit()
        expected = (str(self.before), str(self.after))
        self.assertEqual((job['before'], job['after']), expected)
        request = self.fixture.store.request(job['id'])
        for side, source in zip(('base', 'head'), expected):
            snapshot = Path(request[side]['checkout'])
            self.assertTrue(snapshot.is_relative_to(self.fixture.store.root))
            self.assertNotIn(source, json.dumps(request))
            self.assertTrue((snapshot / 'project/project.godot').is_file())
        response, page, _ = self.fixture.http('GET', f"/viewers/{job['id']}/{viewer.EXPORT_NAME}")
        self.assertEqual(response, 200)
        for path in expected:
            self.assertNotIn(path.encode(), page)
        self.after.rename(self.fixture.root / 'Renamed after verification')
        reopened = app.App(self.fixture.store, self.fixture.start).history()['jobs'][0]
        self.assertFalse(reopened['sessionOwned'])
        self.assertEqual((reopened['before'], reopened['after']), expected)

    def test_previous_commit_source_survives_cleanup_and_is_local_display_only(self):
        fixture = self.fixture
        project = self.before
        git = ['git', '-C', str(project), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@localhost']
        subprocess.run(git + ['init', '-q'], check=True)
        subprocess.run(git + ['add', '.'], check=True)
        subprocess.run(git + ['commit', '-qm', 'Original'], check=True)
        parent = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
        subprocess.run(git + ['commit', '--allow-empty', '-qm', 'Next'], check=True)
        code, copy, _ = fixture.http('POST', '/api/projects/previous', {'after': str(project)})
        self.assertEqual(code, 200, copy)
        self.assertEqual(copy['commit'], parent)
        self.before = Path(copy['folder'])
        job = self.submit()  # The After folder differs from the repository that supplied Before.
        expected = f'{project} (copy opened from Git commit {parent})'
        self.assertEqual((job['before'], job['after']), (expected, str(self.after)))
        key = job['id']
        saved = fixture.store.request(key)
        self.assertNotIn(parent, json.dumps(saved))
        code, evidence, _ = fixture.http('GET', f'/viewers/{key}/{viewer.EXPORT_NAME}')
        self.assertEqual(code, 200)
        self.assertNotIn(parent.encode(), evidence)
        self.assertNotIn(str(project).encode(), evidence)
        fixture.server.app.close()
        self.assertFalse(self.before.exists())
        reopened, = app.App(fixture.store, fixture.start).history()['jobs']
        self.assertEqual((reopened['id'], reopened['before'], reopened['after']), (key, expected, str(self.after)))
        self.assertEqual(fixture.store.request(key), saved)

    def test_missing_corrupt_oversized_and_linked_metadata_show_only_the_recorded_checkouts(self):
        job = self.submit()
        key = job['id']
        sidecar = self.fixture.store.root / f'app-folders-{key}.json'
        sidecar.unlink()
        outside = self.fixture.root / 'sentinel.json'
        outside.write_text(json.dumps({'before': '/unrelated/sentinel', 'after': '/unrelated/file'}))
        request = self.fixture.store.request(key)
        for kind in ('missing', 'malformed', 'bad paths', 'invalid commit', 'oversized', 'symlink'):
            with self.subTest(kind=kind):
                if kind == 'malformed':
                    sidecar.write_bytes(b'{}junk')
                elif kind == 'bad paths':
                    sidecar.write_text(json.dumps({'before': '../other', 'after': '/unrelated/file'}))
                elif kind == 'invalid commit':
                    sidecar.write_text(json.dumps({'before': '/unrelated/a', 'after': '/unrelated/b',
                                                   'beforeCommit': 'HEAD'}))
                elif kind == 'oversized':
                    sidecar.write_bytes(outside.read_bytes() + b' ' * app.LIMIT)
                elif kind == 'symlink':
                    sidecar.symlink_to(outside)
                status = self.fixture.server.app.status(key)
                for field, arm in (('before', 'base'), ('after', 'head')):
                    self.assertIn('original selection unavailable', status[field])
                    self.assertIn(request[arm]['checkout'], status[field])
                    self.assertNotIn('unrelated', status[field])
                sidecar.unlink(missing_ok=True)

    def test_reusing_an_existing_job_does_not_replace_its_selections(self):
        job = self.submit()
        self.before = test_app_projects.configured_project(self.fixture.root / 'Other game before')
        self.after = self.fixture.root / 'Other game after'
        shutil.copytree(self.before, self.after)
        previous = self.fixture.store.status(job['id'])
        with mock.patch.object(self.fixture.store, 'create', return_value=(previous, False)):
            same_job = self.submit()
        self.assertEqual((same_job['id'], same_job['before'], same_job['after']),
                         (job['id'], job['before'], job['after']))

    def test_display_metadata_write_failure_does_not_stop_the_worker(self):
        with mock.patch.object(self.fixture.server.app, 'record_folders', side_effect=OSError('disk full')):
            job = self.submit()
        self.assertEqual(job['phase'], 'completed')
        self.assertIn('original selection unavailable', job['after'])


def browser_rehearsal():
    """Run with python3 -m tests.test_app_selected_folders; uses Chromium and the offline worker."""
    from playwright.sync_api import expect, sync_playwright

    test = SelectedFoldersTest()
    try:
        test.setUp()
        fixture = test.fixture
        # A job as stored by older releases: only the immutable checkouts are in its request.
        legacy_req = project_job.prepare(fixture.store, test.after, test.before, require_ready=True)
        legacy, _ = fixture.store.create(legacy_req)
        fixture.store.finish(legacy['id'], 'cancelled')

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=shutil.which('chromium'), headless=True,
                                                 args=['--no-sandbox'])
            try:
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda exc: errors.append(str(exc)))
                def open_app():
                    page.goto(f'http://127.0.0.1:{fixture.port}/?token={fixture.token}')

                open_app()
                page.locator('#before').fill(str(test.before))
                page.locator('#after').fill(str(test.after / 'project.godot'))
                with page.expect_response(lambda response: response.url.endswith('/api/jobs')
                                          and response.request.method == 'POST') as submitted:
                    with page.expect_response(lambda response: response.url.endswith('/api/inspect')) as checked:
                        page.locator('#verify').click()
                    if checked.value.json().get('rendering', {}).get('warning'):
                        page.get_by_role('button', name='Verify with this warning').click()
                reply = submitted.value
                test.assertEqual(reply.status, 201)
                job = fixture.finished(reply.json()['id'])
                test.assertEqual(job['phase'], 'completed')
                expected = [str(test.before), str(test.after)]
                shown = page.locator('#result-folders dd')
                expect(shown).to_have_text(expected)
                expect(page.locator('#verify')).to_have_text('Verify')
                page.locator('#before').fill('Changed after the run')
                expect(page.locator('#past-runs li').filter(has_text=str(test.before))).to_have_count(1)
                page.locator('#past-runs li').filter(has_text=str(test.before)).get_by_role('link').click()
                expect(shown).to_have_text(expected)
                expect(page.locator('#before')).to_have_value('Changed after the run')

                fixture.close()
                fixture.server = app.create_server(fixture.store, start=fixture.start)
                fixture.thread = threading.Thread(target=fixture.server.serve_forever, daemon=True)
                fixture.thread.start()
                fixture.port, fixture.token = fixture.server.server_port, fixture.server.token
                open_app()
                page.locator('#past-runs li').filter(has_text=str(test.before)).get_by_role('link').click()
                expect(shown).to_have_text(expected)
                page.locator('#past-runs li').filter(has_text='original selection unavailable').get_by_role('link').click()
                for i, arm in enumerate(('base', 'head')):
                    expect(shown.nth(i)).to_contain_text('original selection unavailable')
                    expect(shown.nth(i)).to_contain_text(legacy_req[arm]['checkout'])
                test.assertEqual(errors, [])
                print(f'Chromium {browser.version}: configured result, edited form, reopened history, '
                      'app restart and older snapshot record passed; zero page errors.')
            finally:
                browser.close()
    finally:
        test.doCleanups()


if __name__ == '__main__':
    browser_rehearsal()
