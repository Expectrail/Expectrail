"""The desktop folder choices on the local app's first screen (#710)."""
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
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

            recent_before = page.get_by_label('Recent Before folders', exact=True)
            recent_after = page.get_by_label('Recent After folders', exact=True)
            expect(recent_before).to_be_hidden()
            expect(recent_after).to_be_hidden()

            submitted = []
            page.on('request', lambda r: submitted.append(r.url.rsplit('/', 1)[-1])
                    if r.method == 'POST' and r.url.endswith(('/api/jobs', '/api/inspect')) else None)

            def verify_with_missing(side):
                page.get_by_role('button', name='Verify', exact=True).click()
                expect(page.locator('#progress')).to_have_text('Verification did not start.')
                expect(page.locator('#'+side)).to_be_focused()
                expect(page.locator('#'+side+'-feedback')).to_contain_text('Choose the '+side.title()+' folder')
                fixture.assertEqual(submitted, [])

            verify_with_missing('before')
            native.return_value = str(before)
            choose_before.focus()
            choose_before.press('Enter')
            expect(before_field).to_have_value(str(before))
            expect(after_field).to_have_value('')
            after_field.fill('  ')
            verify_with_missing('after')
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
            expect(recent_before.locator('option')).to_have_text(
                ['Choose a recent folder', str(before), str(another), str(after)])
            recent_before.focus()
            recent_before.press('ArrowDown')
            expect(before_field).to_have_value(str(before))
            recent_before.press('ArrowDown')
            expect(before_field).to_have_value(str(another))
            recent_before.press('ArrowUp')
            expect(before_field).to_have_value(str(before))
            expect(recent_before).to_have_value(str(before))
            recent_before.select_option(str(before))
            expect(before_field).to_have_value(str(before))
            expect(page.locator('#before-feedback')).to_contain_text('Before folder selected.')
            expect(after_field).to_have_value(str(after / 'project.godot'))

            # Reopening the local app loads the saved list. An entry can have moved since it was saved.
            (another / 'project.godot').unlink()
            page.goto(f'http://127.0.0.1:{fixture.port}/?token={fixture.token}')
            recent_after.select_option(str(another))
            expect(after_field).to_have_value(str(another))
            expect(feedback).to_contain_text('Choose the folder containing')
            expect(before_field).to_have_value('')
            after_field.fill(str(after))
            expect(feedback).to_be_empty()
            expect(recent_after).to_have_value('')

            with page.expect_response(lambda response: response.url.endswith('/api/projects/check')):
                def edit_before_reply(route):
                    after_field.fill(str(before))
                    route.continue_()

                page.route('**/api/projects/check', edit_before_reply, times=1)
                recent_after.select_option(str(another))
            page.wait_for_load_state('networkidle')
            expect(after_field).to_have_value(str(before))
            expect(feedback).to_be_empty()
            fixture.assertEqual(requests, [('POST', {})] * 6)
            fixture.assertEqual(native.call_count, 6)
            fixture.assertEqual(fixture.server.app.history()['jobs'], [])
            fixture.assertEqual(errors, [])
            fixture.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
            print(f'Chromium {browser.version}: both folder buttons, cancellation, review invalidation, '
                  'concurrent chooser prevention, manual-edit preservation and field errors passed. '
                  'Recent folders reopened on both sides, with stale entries and late replies checked. '
                  '6 empty-body chooser requests, 0 jobs, 0 page errors, no overflow at 390 px.')
            rehearse_before_suggestion(browser, fixture, native)
            rehearse_previous_commit(browser, fixture)
            rehearse_folder_drop(browser, fixture, native)
            rehearse_folder_pair(browser, fixture, native)
            browser.close()
    finally:
        release.set()
        fixture.doCleanups()


def rehearse_before_suggestion(browser, fixture, native):
    from playwright.sync_api import expect

    after = test_app_projects.configured_project(fixture.root / 'Garden-after')
    before = test_app_projects.configured_project(fixture.root / 'Garden-before')
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    url = f'http://127.0.0.1:{fixture.port}/?token={fixture.token}'
    page.goto(url)
    before_field, after_field = page.locator('#before'), page.locator('#after')
    use = page.get_by_role('button', name='Use as Before', exact=True)
    native.return_value = str(after)
    page.get_by_role('button', name='Choose After folder', exact=True).click()
    expect(use).to_be_visible()
    expect(page.locator('#suggested-folder')).to_have_text(str(before))
    expect(before_field).to_have_value('')
    fixture.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
    use.focus()
    use.press('Enter')
    expect(before_field).to_have_value(str(before))
    expect(use).to_be_hidden()
    page.get_by_role('button', name='Check folders').click()
    expect(page.locator('#inspection-before')).to_contain_text('smoke')
    expect(page.locator('#inspection-after')).to_contain_text('smoke')

    page.goto(url)
    recent = page.get_by_label('Recent After folders', exact=True)
    recent.select_option(str(after))
    expect(use).to_be_visible()
    before_field.fill('my own choice')
    expect(use).to_be_hidden()
    recent.select_option(str(after))
    expect(page.locator('#after-feedback')).to_contain_text('After folder selected.')
    expect(use).to_be_hidden()
    expect(before_field).to_have_value('my own choice')

    before_field.fill('')
    after_field.fill(str(after / 'project.godot'))
    after_field.press('Tab')
    expect(use).to_be_visible()
    after_field.fill(str(fixture.root))
    expect(use).to_be_hidden()
    with page.expect_response(lambda response: response.url.endswith('/api/projects/check')):
        after_field.press('Tab')

    def edit_while_checking(route):
        reply = route.fetch()
        # Both fields return to their original values before the older reply arrives.
        before_field.fill('my own choice')
        before_field.fill('')
        route.fulfill(response=reply)

    page.route('**/api/projects/check', edit_while_checking, times=1)
    with page.expect_response(lambda response: response.url.endswith('/api/projects/check')):
        recent.select_option(str(after))
    expect(page.locator('#after-feedback')).to_contain_text('After folder selected.')
    expect(use).to_be_hidden()
    expect(before_field).to_have_value('')
    fixture.assertEqual(fixture.server.app.history()['jobs'], [])
    page.close()


def rehearse_previous_commit(browser, fixture):
    from playwright.sync_api import expect

    checkout = fixture.root / 'Orbit checkout'
    after = test_app_projects.configured_project(checkout / 'game')
    git = ['git', '-C', str(checkout), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid']
    subprocess.run(git + ['init', '-q'], check=True)
    subprocess.run(git + ['add', '.'], check=True)
    subprocess.run(git + ['commit', '-qm', 'Original game'], check=True)
    parent = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
    original = (after / 'entry.tscn').read_bytes()

    page = browser.new_page(viewport={'width': 390, 'height': 844})
    previous_requests = []
    page.on('request', lambda req: previous_requests.append(req.post_data_json)
            if req.url.endswith('/api/projects/previous') else None)
    page.goto(f'http://127.0.0.1:{fixture.port}/?token={fixture.token}')
    before_field, after_field = page.locator('#before'), page.locator('#after')
    use = page.get_by_role('button', name='Use previous commit as Before', exact=True)
    after_field.fill(str(after))
    after_field.press('Tab')
    expect(use).to_be_visible()
    fixture.assertEqual(previous_requests, [])
    use.click()
    expect(page.locator('#before-feedback')).to_contain_text('Choose a Before folder')
    expect(before_field).to_have_value('')

    (after / 'entry.tscn').write_bytes(original + b'\n')
    subprocess.run(git + ['commit', '-qam', 'Changed game'], check=True)
    use.focus()
    use.press('Enter')
    expect(page.locator('#before-feedback')).to_contain_text(parent[:12])
    expect(before_field).to_be_focused()
    fixture.assertEqual((Path(before_field.input_value()) / 'entry.tscn').read_bytes(), original)
    expect(after_field).to_have_value(str(after))
    fixture.assertEqual((after / 'entry.tscn').read_bytes(), original + b'\n')
    expect(use).to_be_hidden()
    page.get_by_role('button', name='Check folders').click()
    expect(page.locator('#inspection-before')).to_contain_text('smoke')
    expect(page.locator('#inspection-after')).to_contain_text('smoke')
    after_field.fill(str(fixture.after))
    expect(before_field).to_have_value('')
    before_field.fill('my own choice')
    after_field.fill(str(after))
    after_field.press('Tab')
    expect(before_field).to_have_value('my own choice')
    expect(use).to_be_hidden()
    before_field.fill('')
    before_field.press('Tab')
    expect(use).to_be_visible()
    fixture.assertEqual(previous_requests, [{'after': str(after)}] * 2)
    fixture.assertEqual(fixture.server.app.history()['jobs'], [])
    page.close()


def rehearse_folder_pair(browser, fixture, native):
    from playwright.sync_api import expect

    game = test_app_projects.configured_project(fixture.root / 'first' / 'Orbit')
    copy = fixture.root / 'second' / 'Orbit'
    shutil.copytree(game, copy)
    other_layout = fixture.root / 'third' / 'Orbit'
    shutil.copytree(game, other_layout)
    (other_layout / 'entry.tscn').rename(other_layout / 'start.tscn')
    config_file = other_layout / 'expectrail.project.json'
    config = json.loads(config_file.read_text())
    config['entryScene'] = 'res://start.tscn'
    config_file.write_text(json.dumps(config))
    fixture.server.app.remember_project(game)

    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(f'http://127.0.0.1:{fixture.port}/?token={fixture.token}')
    before, after = page.locator('#before'), page.locator('#after')
    note = page.locator('#folder-pair-feedback')

    def select_after_during_single_check(route):
        reply = route.fetch()
        page.get_by_label('Recent After folders', exact=True).select_option(str(game))
        route.fulfill(response=reply)

    page.route('**/api/projects/check', select_after_during_single_check, times=1)
    page.get_by_label('Recent Before folders', exact=True).select_option(str(game))
    expect(note).to_contain_text('same copy')
    expect(page.locator('#before-feedback')).to_have_text('Before folder selected.')
    expect(note).to_contain_text('Choose Before folder')
    expect(note).to_contain_text('verify this copy as a baseline')

    unconfigured = test_app_projects.configured_project(fixture.root / 'unconfigured')
    (unconfigured / 'expectrail.project.json').unlink()
    before.fill(str(unconfigured))
    after.fill(str(unconfigured / 'project.godot'))
    expect(page.locator('#before-feedback')).to_contain_text('Check folders')
    expect(note).to_contain_text('same copy')
    expect(note).to_contain_text('Choose Before folder')
    page.get_by_role('button', name='Verify', exact=True).click()
    expect(page.locator('#progress')).to_have_text('Verification did not start.')
    fixture.assertEqual(fixture.server.app.history()['jobs'], [])
    expect(note).not_to_contain_text('verify this copy as a baseline')
    before.fill(str(game))

    def checked_pair(response, left, right):
        return (response.url.endswith('/api/projects/check')
                and response.request.post_data_json == {'before': str(left), 'after': str(right)})

    descriptor = game / 'project.godot'
    with page.expect_response(lambda r: checked_pair(r, game, descriptor)):
        after.fill(str(descriptor))
    expect(note).to_contain_text('same copy')
    # Separate directories with identical names and bytes are a valid pair.
    native.return_value = str(copy)
    with page.expect_response(lambda r: checked_pair(r, copy, descriptor)):
        page.get_by_role('button', name='Choose Before folder', exact=True).click()
    expect(note).to_be_empty()

    # Changing the scene bytes in a separate copy must not turn it into the same folder.
    (copy / 'entry.tscn').write_text((copy / 'entry.tscn').read_text() + '\n')
    with page.expect_response(lambda r: checked_pair(r, copy, game)):
        after.fill(str(game))
    expect(note).to_be_empty()

    after.fill(str(other_layout))
    after_feedback = page.locator('#after-feedback')
    expect(after_feedback).to_contain_text('different layouts')
    expect(after_feedback).to_contain_text('entry.tscn')
    before.fill('')
    expect(after_feedback).not_to_contain_text('different layouts')
    expect(note).to_be_empty()
    before.fill(str(game))
    expect(after_feedback).to_contain_text('different layouts')
    after.fill('')
    expect(after_feedback).not_to_contain_text('different layouts')
    before.fill('')

    # An older same-copy reply must not restore the warning after another selection.
    after.fill(str(game))
    delayed = []

    def clear_before_reply(route):
        if route.request.post_data_json != {'before': str(descriptor), 'after': str(game)}:
            route.continue_()
            return
        reply = route.fetch()
        before.fill('')
        delayed.append(True)
        route.fulfill(response=reply)

    page.route('**/api/projects/check', clear_before_reply)
    with page.expect_response(lambda r: checked_pair(r, descriptor, game)):
        before.fill(str(descriptor))
    page.wait_for_load_state('networkidle')
    page.unroute('**/api/projects/check', clear_before_reply)
    fixture.assertEqual(delayed, [True])
    expect(before).to_have_value('')
    expect(note).to_be_empty()

    def verify_while_checking(left):
        # Hold the actual pair reply until after the developer clicks Verify.
        held = []

        def hold(route):
            held.append(route)

        page.route('**/api/projects/check', hold)
        with page.expect_request(lambda r: r.url.endswith('/api/projects/check')
                                 and r.post_data_json == {'before': str(left), 'after': str(game)}):
            before.fill(str(left))
            expect(note).to_be_empty()
        page.locator('#verify').click()
        fixture.assertEqual(len(held), 1)
        with page.expect_response(lambda r: checked_pair(r, left, game)):
            held[0].fulfill(response=held[0].fetch())
        page.unroute('**/api/projects/check', hold)

    preflight = []
    page.on('request', lambda r: preflight.append(r.url)
            if r.method == 'POST' and r.url.endswith(('/api/inspect', '/api/jobs')) else None)
    verify_while_checking(descriptor)
    expect(note).to_contain_text('same copy')
    expect(before).to_be_enabled()
    expect(page.locator('#choose-before')).to_be_focused()
    fixture.assertEqual(preflight, [])
    fixture.assertEqual(fixture.server.app.history()['jobs'], [])
    expect(page.locator('#verify')).to_be_enabled()

    def submit(action):
        with page.expect_response(lambda r: r.url.endswith('/api/jobs') and r.request.method == 'POST') as submitted:
            with page.expect_response(lambda r: r.url.endswith('/api/inspect')) as inspected:
                action()
            if inspected.value.json().get('rendering', {}).get('warning'):
                page.get_by_role('button', name='Verify with this warning').click()
        fixture.assertEqual(submitted.value.status, 201)
        return fixture.finished(submitted.value.json()['id'])

    baseline = submit(page.locator('#verify').click)
    fixture.assertEqual((baseline['before'], baseline['after']), (str(game), str(game)))
    fixture.assertEqual(len(fixture.server.app.history()['jobs']), 1)

    distinct = submit(lambda: verify_while_checking(copy))
    fixture.assertEqual((distinct['before'], distinct['after']), (str(copy), str(game)))
    fixture.assertEqual(len(fixture.server.app.history()['jobs']), 2)
    fixture.assertEqual(errors, [])
    print(f'Chromium {browser.version}: same-copy warning for recent folders and project.godot; '
          'distinct identical copies, layout warning, clearing and late replies checked. '
          'An early Verify click paused for the same copy and continued for distinct copies. '
          'The deliberate baseline and the distinct comparison used the test replay backend.')
    page.close()


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

    with page.expect_response(lambda r: r.url.endswith('/api/projects/check') and 'before' in r.request.post_data_json):
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
    fixture.assertEqual(posts, [('choose', {}), ('choose', {}),
                                ('check', {'before': str(before), 'after': str(after)}), ('choose', {})])
    fixture.assertEqual(fixture.server.app.history()['jobs'], [])
    fixture.assertEqual(len(page.context.pages), 1)
    print('Folder drops: confirmed both paths through the desktop chooser stand-in, preserved a cancelled '
          'choice, and ignored invalid or untargeted drops. Three empty-body chooser requests, one check of the confirmed pair, one tab, zero jobs.')
    page.close()


if __name__ == '__main__':
    browser_rehearsal()
