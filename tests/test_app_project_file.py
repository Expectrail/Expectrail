"""Configured app paths can identify a project by its Godot descriptor (#704)."""
import json
import os
from pathlib import Path
import unittest

from expectrail import onboard
from expectrail.orchestrator import request
from tests import test_app, test_app_projects, test_inspect_atlas


class ProjectFileTest(unittest.TestCase):
    def setUp(self):
        self.app = test_app.HTTPTest()
        self.addCleanup(self.app.doCleanups)
        self.app.setUp()

    def post(self, endpoint, fields, expected):
        code, data, _ = self.app.http('POST', '/api/' + endpoint, fields)
        self.assertEqual(code, expected, data)
        return data

    def test_configured_file_inputs_inspect_and_submit_the_containing_projects(self):
        before = test_app_projects.configured_project(self.app.root / 'Original game')
        after = test_app_projects.configured_project(self.app.root / 'Changed game')
        config = after / 'expectrail.project.json'
        config.write_text(json.dumps(json.loads(config.read_text()) | {'routes': []}))

        paths = {side: str(root / 'project.godot') for side, root in [('before', before), ('after', after)]}
        for side, root in [('before', before), ('after', after)]:
            result = self.post('inspect', {'side': side, 'folder': paths[side]}, 200)
            self.assertEqual(result['folder'], str(root))
            self.assertTrue(result['godot'])
            self.assertEqual(result['routes'], 1 if side == 'before' else 0)

        job = self.post('jobs', paths, 201)
        result = self.app.finished(job['id'])
        self.assertEqual(result['state'], 'needs-review', result)
        saved = self.app.store.request(job['id'])
        self.assertEqual(len(request.read_checks(saved).routes), 1)
        for key, root in [('base', before), ('head', after)]:
            snapshot = Path(saved[key]['checkout'])
            self.assertEqual(request.tree_digest(snapshot / 'project'), request.tree_digest(root))

    def test_file_preview_and_reviewed_save_check_the_same_folder_and_current_bytes(self):
        project = test_inspect_atlas.AtlasReviewTest()
        self.addCleanup(project.doCleanups)
        project.setUp()
        game = project.game
        descriptor = game / 'project.godot'
        fields = {'side': 'before', 'folder': str(descriptor)}

        preview = self.post('inspect', fields, 400)['setupPreview']
        self.assertCountEqual(preview['players'], ['Paddle', 'Ball'])
        fields['player'] = 'Paddle'

        def review():
            info = self.post('inspect', fields, 400)['setupPreview']['saveReview']
            self.assertEqual(info['folder'], str(game))
            return fields | {'review': info['id']}

        stale = review()
        with descriptor.open('a') as stream:
            stream.write('\n; edited after review\n')
        self.assertIn('changed', self.post('setup/save', stale, 400)['detail'])
        self.assertFalse((game / onboard.PENDING).exists())
        current = review()
        original = descriptor.read_bytes()
        duplicate = self.app.root / 'descriptor-copy'
        duplicate.write_bytes(original)
        descriptor.unlink()
        descriptor.symlink_to(duplicate)
        self.assertIn('symbolic link', self.post('setup/save', current, 400)['detail'])
        self.assertFalse((game / onboard.PENDING).exists())
        descriptor.unlink()
        descriptor.write_bytes(original)

        current = review()
        saved = self.post('setup/save', current, 201)
        self.assertEqual(saved['setupFile'], onboard.PENDING)
        self.assertTrue((game / saved['route']).is_file())
        self.assertIn('Saved draft preview', self.post('inspect', {'folder': str(descriptor)}, 400)['detail'])
        self.post('setup/save', current, 400)
        self.assertEqual(self.app.server.app.history()['jobs'], [])

    def test_manual_checkouts_still_require_folder_paths(self):
        descriptor = self.app.before / 'game/platformer/project.godot'
        fields = self.app.body | {'folder': str(descriptor), 'projectConfig': False, 'game': '.'}
        manual = self.post('inspect', fields, 200)
        self.assertFalse(manual['godot'])
        self.assertEqual(manual['folder'], str(descriptor))
        self.post('jobs', fields | {'before': str(descriptor)}, 400)
        self.assertEqual(self.app.server.app.history()['jobs'], [])

    def test_invalid_files_and_symlinked_descriptors_never_select_a_project(self):
        game = test_app_projects.configured_project(self.app.root / 'Ready game')
        missing = self.app.root / 'missing' / 'project.godot'
        invalid = [game / 'entry.tscn', missing]
        for label, target in [('linked file', game / 'project.godot'), ('linked folder', game),
                              ('dangling', missing)]:
            link = self.app.root / label / 'project.godot'
            link.parent.mkdir()
            link.symlink_to(target)
            invalid.append(link)
        if hasattr(os, 'mkfifo'):
            fifo = self.app.root / 'pipe' / 'project.godot'
            fifo.parent.mkdir()
            os.mkfifo(fifo)
            invalid.append(fifo)

        for path in invalid:
            with self.subTest(path=path):
                error = self.post('inspect', {'folder': str(path)}, 400)
                self.assertNotIn('setupPreview', error)
                for side in ('before', 'after'):
                    fields = {'before': str(game), 'after': str(game), side: str(path)}
                    error = self.post('jobs', fields, 400)
                    self.assertIs(error.get('jobStarted'), False)
        self.assertEqual(self.app.server.app.history()['jobs'], [])
