"""The desktop folder choices on the local app's first screen (#710)."""
from html.parser import HTMLParser
import importlib.util
import shutil
import threading
import unittest
from unittest import mock

from expectrail import app, app_page
from tests import test_app, test_app_projects


class ChoiceMarkup(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.elements = {}
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if 'id' in props:
            self.elements[props['id']] = (tag, props)


class DesktopChooserTest(unittest.TestCase):
    def test_choosing_folders_in_chromium(self):
        if not (shutil.which('chromium') or shutil.which('chromium-browser')):
            self.skipTest('Chromium is not installed')
        if importlib.util.find_spec('playwright') is None:
            self.skipTest('Playwright is not installed')
        browser_rehearsal()

    def test_each_folder_has_a_keyboard_button_and_field_feedback(self):
        page = ChoiceMarkup(app_page.PAGE)
        for side in ('before', 'after'):
            with self.subTest(side=side):
                tag, button = page.elements[f'choose-{side}']
                self.assertEqual((tag, button.get('type')), ('button', 'button'))
                tag, field = page.elements[side]
                self.assertEqual(tag, 'input')
                self.assertEqual(page.elements[field['aria-describedby']][1]['role'], 'status')


def browser_rehearsal():
    """Run with python3 -m tests.test_app_desktop_chooser on a machine with Chromium and Playwright."""
    from playwright.sync_api import expect, sync_playwright

    fixture = test_app.HTTPTest()
    release = threading.Event()
    try:
        fixture.setUp()
        before = test_app_projects.configured_project(fixture.root / 'My game before')
        after = test_app_projects.configured_project(fixture.root / 'My game after')
        another = test_app_projects.configured_project(fixture.root / 'Another before')
        with sync_playwright() as playwright, mock.patch.object(app, 'choose_folder') as native:
            browser = playwright.chromium.launch(executable_path=shutil.which('chromium') or shutil.which('chromium-browser'),
                                                 headless=True,
                                                 args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            errors, requests = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append((request.method, request.post_data_json))
                    if request.url.endswith('/api/projects/choose') else None)
            page.goto(f'http://127.0.0.1:{fixture.port}/?token={fixture.token}')
            choose_before = page.get_by_role('button', name='Choose Before folder', exact=True)
            choose_after = page.get_by_role('button', name='Choose After folder', exact=True)
            before_field, after_field = page.locator('#before'), page.locator('#after')

            native.return_value = str(before)
            choose_before.focus()
            choose_before.press('Enter')
            expect(before_field).to_have_value(str(before))
            expect(after_field).to_have_value('')
            native.return_value = str(after)
            choose_after.click()
            expect(after_field).to_have_value(str(after))
            page.get_by_role('button', name='Check folders').click()
            checked = page.locator('#inspection-before')
            expect(checked).to_contain_text('smoke')
            native.return_value = None
            choose_before.click()
            expect(choose_before).to_be_enabled()
            expect(before_field).to_have_value(str(before))
            expect(checked).to_contain_text('smoke')

            native.return_value = str(another)
            choose_before.click()
            expect(before_field).to_have_value(str(another))
            expect(checked).to_be_empty()
            expect(page.locator('#inspection-after')).to_contain_text('smoke')

            def delayed_choice():
                if not release.wait(15):
                    raise RuntimeError('Native chooser stand-in timed out')
                return str(before)

            native.side_effect = delayed_choice
            choose_before.click()
            expect(choose_after).to_be_disabled()
            expect(page.get_by_role('button', name='Verify', exact=True)).to_be_disabled()
            manual = str(before / 'project.godot')
            before_field.fill(manual)
            release.set()
            expect(choose_before).to_be_enabled()
            expect(before_field).to_have_value(manual)

            native.side_effect = None
            native.return_value = str(fixture.root)
            choose_after.click()
            expect(choose_after).to_be_enabled()
            feedback = page.locator('#' + after_field.get_attribute('aria-describedby'))
            expect(feedback).to_contain_text('Choose the folder containing it.')
            expect(after_field).to_have_value(str(after))
            after_field.fill(str(after / 'project.godot'))
            expect(feedback).to_be_empty()
            fixture.assertEqual(requests, [('POST', {})] * 6)
            fixture.assertEqual(native.call_count, 6)
            fixture.assertEqual(fixture.server.app.history()['jobs'], [])
            fixture.assertEqual(errors, [])
            fixture.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
            print(f'Chromium {browser.version}: both folder buttons, cancellation, review invalidation, '
                  'concurrent chooser prevention, manual-edit preservation and field errors passed. '
                  '6 empty-body chooser requests, 0 jobs, 0 page errors, no overflow at 390 px.')
            rehearse_folder_drop(browser, fixture, native)
            browser.close()
    finally:
        release.set()
        fixture.doCleanups()


def rehearse_folder_drop(browser, fixture, native):
    from playwright.sync_api import expect

    before = test_app_projects.configured_project(fixture.root / 'original' / 'OrbitGame')
    after = test_app_projects.configured_project(fixture.root / 'changed' / 'OrbitGame')
    page = browser.new_page()
    posts = []
    page.on('request', lambda req: posts.append((req.url.rsplit('/', 1)[-1], req.post_data_json))
            if req.method == 'POST' else None)
    page.goto(f'http://127.0.0.1:{fixture.port}/?token={fixture.token}')
    session = page.context.new_cdp_session(page)

    def drop(target, *paths):
        target.scroll_into_view_if_needed()
        box = target.bounding_box()
        data = {'files': [str(path) for path in paths], 'items': [], 'dragOperationsMask': 1}
        for event in ('dragEnter', 'dragOver', 'drop'):
            session.send('Input.dispatchDragEvent', {
                'type': event, 'x': box['x'] + box['width'] / 2, 'y': box['y'] + box['height'] / 2,
                'data': data})

    for side, folder in [('before', before), ('after', after)]:
        native.return_value = str(folder)
        field = page.locator('#' + side)
        # Only the desktop selection distinguishes these identically named folders.
        drop(field, before)
        expect(field).to_have_value(str(folder))
    native.return_value = None
    drop(page.locator('#before'), after)
    expect(page.locator('#before-feedback')).to_contain_text('cancelled')
    expect(page.locator('#before')).to_have_value(str(before))
    expect(page.locator('#after')).to_have_value(str(after))
    for paths in [(after / 'pawn.svg',), (before, after)]:
        drop(page.locator('#after'), *paths)
        expect(page.locator('#after-feedback')).to_contain_text('Drop one project folder')
        expect(page.locator('#after')).to_have_value(str(after))
    drop(page.locator('#run-heading'), after)
    fixture.assertEqual(posts, [('choose', {})] * 3)
    fixture.assertEqual(fixture.server.app.history()['jobs'], [])
    fixture.assertEqual(len(page.context.pages), 1)
    print('Folder drops: confirmed both paths through the desktop chooser stand-in, preserved a cancelled '
          'choice, and ignored invalid or untargeted drops. Three empty-body chooser requests, one tab, zero jobs.')
    page.close()


if __name__ == '__main__':
    browser_rehearsal()
