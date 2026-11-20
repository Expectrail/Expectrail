"""Only a confirmed, current player inspection can publish a browser setup."""
import importlib.util
import json
import shutil
import unittest
from unittest import mock

from expectrail import input_discovery, onboard
from tests import test_app, test_inspect_atlas as atlas


class SaveSetupTest(unittest.TestCase):
    def setUp(self):
        self.app = test_app.HTTPTest()
        self.addCleanup(self.app.doCleanups)
        self.app.setUp()
        project = atlas.AtlasReviewTest()
        self.addCleanup(project.doCleanups)
        project.setUp()
        self.game = project.game
        self.fields = {'folder': str(self.game), 'side': 'before', 'player': 'Paddle'}

    def review(self, **fields):
        body = {**self.fields, **fields}
        status, response, _ = self.app.http('POST', '/api/inspect', body)
        self.assertEqual(status, 400, response)
        preview = response['setupPreview']
        return {**body, 'review': preview['saveReview']['id']}, preview['saveReview']

    def save(self, body, expected):
        status, response, _ = self.app.http('POST', '/api/setup/save', body)
        self.assertEqual(status, expected, response)
        self.assertEqual(self.app.server.app.history()['jobs'], [])
        return response

    def test_review_then_write_one_pending_pair_without_running_engine(self):
        original = atlas.digest(self.game)
        with mock.patch.object(input_discovery, 'probe', side_effect=AssertionError('unexpected probe')):
            body, review = self.review()
            self.assertFalse(review['runsProject'])
            self.assertEqual(review['setupFile'], onboard.PENDING)
            self.assertEqual(atlas.digest(self.game), original)
            response = self.save(body, 201)
        route = response['route']
        self.assertRegex(route, r'^routes/draft-first-[0-9a-f]{16}\.json$')
        self.assertEqual(response['setupFile'], onboard.PENDING)
        self.assertEqual(original.keys() | {route, onboard.PENDING}, atlas.digest(self.game).keys())
        saved = json.loads((self.game / onboard.PENDING).read_bytes())
        self.assertEqual(saved['config']['bindings']['player'], {'node': 'Paddle'})
        self.assertEqual(saved['imageSuggestions'][0]['regions'], [[0, 0, 47, 18], [47, 0, 47, 18]])
        self.assertFalse(saved['config'].get('approvedContracts'))
        self.save(body, 400)

    def test_resolved_player_gets_a_draft_config_without_approval(self):
        body, review = self.review(player='Ball')
        self.assertEqual(review['setupFile'], onboard.ACTIVE)
        self.save(body, 201)
        config = json.loads((self.game / onboard.ACTIVE).read_bytes())
        self.assertTrue(config['draft'])
        self.assertFalse(config.get('approvedContracts'))
        self.assertEqual(config['bindings']['player'], {'node': 'Ball', 'texture': atlas.BALL})

    def test_wrong_absent_superseded_or_injected_review_cannot_write(self):
        original = atlas.digest(self.game)
        self.save(self.fields, 400)
        first, _ = self.review()
        for modified in ({'side': 'after'}, {'folder': str(self.app.after)}, {'player': 'Ball'},
                         {'filename': 'custom.json'}, {'config': {}}):
            self.save({**first, **modified}, 400)
        self.review(player='Ball')
        self.save(first, 400)
        self.assertEqual(atlas.digest(self.game), original)

    def test_stale_project_or_new_setup_blocks_before_probe_or_publication(self):
        with mock.patch.object(input_discovery, 'probe', side_effect=AssertionError('unexpected probe')):
            for name in ('changed.gd', onboard.ACTIVE, onboard.PENDING):
                with self.subTest(name=name):
                    body, _ = self.review()
                    path = self.game / name
                    path.write_text('new bytes')
                    before = atlas.digest(self.game)
                    self.save(body, 400)
                    self.assertEqual(atlas.digest(self.game), before)
                    path.unlink()

    def test_browser_shows_destination_and_can_dismiss_then_confirm(self):
        chromium = shutil.which('chromium') or shutil.which('chromium-browser')
        if not chromium or importlib.util.find_spec('playwright') is None:
            self.skipTest('Chromium and Playwright are required')
        from playwright.sync_api import expect, sync_playwright

        original = atlas.digest(self.game)
        other = self.app.root / 'another project'
        shutil.copytree(self.game, other)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=chromium, args=['--no-sandbox'])
            page = browser.new_page()
            page.goto(f'http://127.0.0.1:{self.app.port}/?token={self.app.token}')
            page.get_by_label('Before: full folder path').fill(str(self.game))
            page.get_by_label('After: full folder path').fill(str(other))
            page.get_by_role('button', name='Check folders').click()
            page.get_by_label('Before player').select_option('Paddle')
            before = page.locator('#inspection-before')
            save = before.get_by_role('button', name='Save draft setup')
            for text in ('Before folder: ' + str(self.game), 'Selected player: Paddle', onboard.PENDING,
                         'routes/', 'without starting the game', '47 × 18', 'human approval'):
                expect(before).to_contain_text(text)
            page.once('dialog', lambda dialog: dialog.dismiss())
            save.click()
            expect(before).to_contain_text('Save cancelled')
            self.assertEqual(atlas.digest(self.game), original)
            page.once('dialog', lambda dialog: dialog.accept())
            save.click()
            expect(before).to_contain_text('Saved ' + onboard.PENDING)
            browser.close()
        self.assertEqual(atlas.digest(other), original)
        self.assertEqual(self.app.server.app.history()['jobs'], [])

    def test_project_changed_while_measuring_is_preserved(self):
        with (self.game / 'game.tscn').open('a') as f:
            f.write('\n[node name="Start" type="Button" parent="."]\n')
        original = atlas.digest(self.game)

        def measure(snapshot, info):
            self.assertNotEqual(snapshot, self.game)
            self.assertEqual(atlas.digest(snapshot), original)
            (self.game / 'new-input.gd').write_text('extends Node')
            return {'tick': 9, 'viewport': [360, 640], 'buttons': [], 'paused': False, 'truncated': False}

        with mock.patch.object(input_discovery, 'probe', side_effect=measure) as probe:
            body, _ = self.review()
            response = self.save(body, 400)
            self.assertIn('project changed', response['detail'])
            probe.assert_called_once()
        self.assertEqual(atlas.digest(self.game).keys(), original.keys() | {'new-input.gd'})

    def test_isolated_selection_refuses_a_required_probe(self):
        with (self.game / 'project.godot').open('a') as f:
            f.write('\n[input]\npause={"deadzone": 0.5, "events": []}\n')
        with mock.patch.object(input_discovery, 'probe', side_effect=AssertionError('unexpected probe')):
            status, response, _ = self.app.http('POST', '/api/inspect', {**self.fields, 'executionClass': 'isolated'})
            self.assertEqual(status, 400)
            review = response['setupPreview']['saveReview']
            self.assertIn('sandbox', review['blocked'])
            self.assertNotIn('id', review)
            self.save({**self.fields, 'review': 'missing'}, 400)

    def test_missing_gameplay_control_refuses_confirmed_save(self):
        with (self.game / 'project.godot').open('a') as f:
            f.write('\n[input]\npause={"deadzone": 0.5, "events": []}\n')
        original = atlas.digest(self.game)
        with mock.patch.object(input_discovery, 'probe', return_value={
            'tick': 9, 'viewport': [360, 640], 'buttons': [], 'paused': False, 'truncated': False,
        }) as probe:
            body, review = self.review(player='Ball')
            self.assertTrue(review['runsProject'])
            probe.assert_not_called()
            result = self.save(body, 400)
            self.assertIn('supply a route', result['detail'])
            probe.assert_called_once()
        self.assertEqual(atlas.digest(self.game), original)
