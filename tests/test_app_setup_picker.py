"""The app previews one selected player's authored image without saving or running."""
import importlib.util
import shutil
import unittest
from unittest import mock

from expectrail import input_discovery, onboarding, renderer
from tests import test_app, test_inspect_atlas as atlas


class SetupPickerTest(unittest.TestCase):
    def setUp(self):
        self.app = test_app.HTTPTest()
        self.addCleanup(self.app.doCleanups)
        self.app.setUp()
        project = atlas.AtlasReviewTest()
        self.addCleanup(project.doCleanups)
        project.setUp()
        self.game = project.game
        for module, name in ((input_discovery, 'probe'), (renderer, 'project_report')):
            patch = mock.patch.object(module, name, side_effect=AssertionError('unexpected probe'))
            self.addCleanup(patch.stop)
            patch.start()

    def inspect(self, **fields):
        status, error, _ = self.app.http('POST', '/api/inspect', {'folder': str(self.game), **fields})
        self.assertEqual(status, 400, error)
        self.assertEqual(error['state'], 'could-not-be-carried-out')
        return error

    def test_choices_images_and_jobs(self):
        original = atlas.digest(self.game)
        preview = self.inspect()['setupPreview']
        self.assertCountEqual(preview['players'], ['Paddle', 'Ball'])
        self.assertIsNone(preview['selectedPlayer'])
        self.assertEqual(preview['imageSuggestions'], [])
        for player, image, size, regions in [('Paddle', atlas.STRIP, [94, 18], [[0, 0, 47, 18], [47, 0, 47, 18]]),
                                             ('Ball', atlas.BALL, [4, 4], None)]:
            report = self.inspect(player=player)['setupPreview']
            self.assertEqual(report['selectedPlayer'], player)
            suggestion, = report['imageSuggestions']
            self.assertEqual((suggestion['image'], suggestion['imageSize'], suggestion['regions']), (image, size, regions))
        body = {'before': str(self.game), 'after': str(self.game), 'player': 'Ball'}
        self.assertEqual(self.app.http('POST', '/api/jobs', body)[0], 400)
        self.assertEqual(self.app.server.app.history()['jobs'], [])
        self.assertEqual(atlas.digest(self.game), original)

    def test_invalid_selections_and_existing_setups(self):
        for player in ('Bat', 'Paddle/AnimatedSprite2D', '', [], None):
            self.assertNotIn('setupPreview', self.inspect(player=player))
        (self.game / atlas.STRIP.removeprefix('res://')).unlink()
        preview = self.inspect(player='Paddle')['setupPreview']
        self.assertEqual(preview['imageSuggestions'], [])
        self.assertIn('Restore ', ' '.join(preview['unresolvedBindings']))
        proposal = onboarding.proposal(self.game, onboarding.inspect(self.game, 'Paddle'))
        onboarding.publish(self.game, proposal, False)
        before = atlas.digest(self.game)
        self.assertIn('Selected player: Paddle', self.inspect()['detail'])
        self.assertNotIn('setupPreview', self.inspect(player='Ball'))
        self.assertEqual(atlas.digest(self.game), before)
        (self.game / 'expectrail.project.json').write_text('{broken')
        self.assertNotIn('setupPreview', self.inspect(player='Ball'))

    def test_browser_keeps_sides_and_pending_selections_independent(self):
        chromium = shutil.which('chromium') or shutil.which('chromium-browser')
        if not chromium or importlib.util.find_spec('playwright') is None:
            self.skipTest('Chromium and Playwright are required')
        from playwright.sync_api import expect, sync_playwright

        other = self.app.root / 'another copy'
        shutil.copytree(self.game, other)
        before = atlas.digest(self.game)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=chromium, args=['--no-sandbox'])
            page = browser.new_page()
            page.goto(f'http://127.0.0.1:{self.app.port}/?token={self.app.token}')
            page.get_by_label('Before: full folder path').fill(str(self.game))
            page.get_by_label('After: full folder path').fill(str(other))
            page.get_by_role('button', name='Check folders').click()
            left = page.get_by_label('Before player')
            right = page.get_by_label('After player')
            left.select_option('Paddle')
            right.select_option('Ball')
            left_result = page.locator('#inspection-before')
            right_result = page.locator('#inspection-after')
            expect(left_result).to_contain_text(str(self.game))
            expect(left_result).to_contain_text('47 × 18 at (47, 0)')
            expect(left_result).not_to_contain_text(atlas.BALL)
            expect(right_result).to_contain_text('4 × 4')
            expect(right_result).to_contain_text('whole image')
            expect(right_result).not_to_contain_text(atlas.STRIP)

            held = []
            def delay_ball(route):
                if route.request.post_data_json.get('player') == 'Ball':
                    held.append(route)
                else:
                    route.continue_()
            page.route('**/api/inspect', delay_ball)
            with page.expect_request(lambda req: req.url.endswith('/api/inspect')):
                left.select_option('Ball')
            left.select_option('Paddle')
            expect(left_result).to_contain_text(atlas.STRIP)
            with page.expect_response(lambda res: res.url.endswith('/api/inspect')):
                held.pop().continue_()
            expect(left_result).not_to_contain_text(atlas.BALL)

            with page.expect_request(lambda req: req.url.endswith('/api/inspect')):
                left.select_option('Ball')
            page.get_by_label('Before: full folder path').fill(str(other))
            with page.expect_response(lambda res: res.url.endswith('/api/inspect')):
                held.pop().continue_()
            expect(left_result).to_be_empty()
            expect(right_result).to_contain_text(atlas.BALL)
            page.unroute('**/api/inspect', delay_ball)
            def delay_initial(route):
                if route.request.post_data_json.get('side') == 'before':
                    held.append(route)
                else:
                    route.continue_()
            page.route('**/api/inspect', delay_initial)
            with page.expect_request(lambda req: req.url.endswith('/api/inspect')):
                page.get_by_role('button', name='Check folders').click()
            page.get_by_label('Before: full folder path').fill(str(self.game), timeout=2000)
            page.get_by_label('After: full folder path').fill(str(self.game), timeout=2000)
            held.pop().continue_()
            expect(page.get_by_role('button', name='Check folders')).to_be_enabled()
            expect(left_result).to_be_empty()
            expect(right_result).to_be_empty()
            browser.close()
        self.assertEqual(self.app.server.app.history()['jobs'], [])
        for folder in (self.game, other):
            self.assertEqual(atlas.digest(folder), before)
