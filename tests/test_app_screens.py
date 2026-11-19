"""Drive the actual local page over HTTP with an offline worker and Chromium."""
import importlib.util
import shutil
import unittest
from unittest import mock

from expectrail.orchestrator.store import diagnostic
from tests import test_app


class AppScreensTest(unittest.TestCase):
    def test_job_screens_and_next_actions(self):
        chromium = shutil.which('chromium') or shutil.which('chromium-browser')
        if not chromium:
            self.skipTest('Chromium is not installed')
        if importlib.util.find_spec('playwright') is None:
            self.skipTest('Playwright is not installed')
        from playwright.sync_api import expect, sync_playwright

        fixture = test_app.HTTPTest()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.starter = lambda store, job_id: None
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=chromium, headless=True,
                                                  args=['--no-sandbox'])
            page = browser.new_page()
            page.route('**/*', lambda route: route.continue_()
                       if route.request.url.startswith(f'http://127.0.0.1:{fixture.port}/')
                       else route.abort())
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{fixture.port}/?token={fixture.token}')
            page.locator('#paths summary').click()
            page.locator('#manual').check()
            for field, value in fixture.body.items():
                page.locator('#' + field).fill(value)

            result = page.locator('#result-text')
            next_step = page.locator('#next-step')
            verify = page.get_by_role('button', name='Verify', exact=True)
            cancel = page.get_by_role('button', name='Cancel', exact=True)
            viewer = page.locator('#viewer')

            def checked(title, guidance, *, active=False, evidence=False):
                expect(result).to_contain_text(title)
                expect(next_step).to_contain_text(guidance)
                if active:
                    expect(cancel).to_be_enabled()
                    expect(verify).to_be_disabled()
                else:
                    expect(cancel).to_be_disabled()
                    expect(verify).to_be_enabled()
                if evidence:
                    expect(viewer).to_be_visible()
                else:
                    expect(viewer).to_be_hidden()

            verify.click()
            checked('Waiting to start', 'Keep this page open', active=True)
            cancel.click()
            checked('Verification cancelled', 'ready to try again', evidence=True)

            with page.expect_response(lambda response: response.url.endswith('/api/jobs') and
                                      response.request.method == 'POST') as submitted:
                verify.click()
            checked('Waiting to start', 'Keep this page open', active=True)
            job_id = submitted.value.json()['id']
            fixture.store.advance(job_id, 'executing')
            checked('Verification is running', 'Follow the progress', active=True)
            expect(page.locator('#progress')).to_have_text('Running the game')
            fixture.store.finish(job_id, 'failed', reasons=['The worker stopped unexpectedly.'])
            checked('Verification stopped unexpectedly', 'share the details', evidence=True)
            expect(page.locator('#details')).to_contain_text('The worker stopped unexpectedly.')

            fixture.starter = None
            with mock.patch.object(fixture.engine, 'preflight', return_value=[
                    diagnostic('TOOL_MISSING', stage='preparing', detail='Install the missing engine.')]):
                require = page.get_by_label('Require the replay sandbox')
                require.check()
                with page.expect_response(lambda response: response.url.endswith('/api/jobs') and
                                          response.request.method == 'POST') as submitted:
                    verify.click()
                isolated_job = submitted.value.json()['id']
                checked('Verification could not be carried out', 'Follow the instructions', evidence=True)
                expect(page.locator('#details')).to_contain_text('Install the missing engine.')
                self.assertEqual(fixture.store.request(isolated_job)['executionClass'], 'isolated')
                expect(page.locator('#isolation')).to_be_hidden()
                require.uncheck()
            self.assertEqual(fixture.server.app.history()['jobs'][0]['decision'], 'needs-review')

            candidate = fixture.after / fixture.body['game']
            for marker, title, guidance in [
                ('BUG', 'Reject', 'what failed'),
                ('CRASH', 'Needs review', 'left unchecked'),
                (None, 'Accept', 'which routes and checks passed'),
            ]:
                with self.subTest(title=title):
                    if marker:
                        (candidate / marker).touch()
                    verify.click()
                    checked(title, guidance, evidence=True)
                    expect(page.locator('#isolation')).to_contain_text('Replays in the sandbox:')
                    if marker:
                        (candidate / marker).unlink()

            page.locator('#after').fill('')
            verify.click()
            checked('Could not be carried out', 'check the folders')
            expect(page.get_by_role('alert')).to_be_visible()
            self.assertEqual(errors, [])
            browser.close()
