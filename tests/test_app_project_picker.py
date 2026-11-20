"""The local project picker uses the app's normal HTTP boundary."""
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest import mock

from expectrail import app
from tests import test_app
from tests.test_app_projects import configured_project


class ProjectPickerTest(unittest.TestCase):
    setUp, close, start, http = (test_app.HTTPTest.setUp, test_app.HTTPTest.close,
                                  test_app.HTTPTest.start, test_app.HTTPTest.http)

    def test_native_choice_requires_auth_and_cannot_be_given_a_path(self):
        picked = configured_project(self.root / 'My game')
        with mock.patch.object(app, 'choose_folder', return_value=str(picked)) as chooser:
            endpoint = '/api/projects/choose'
            self.assertEqual(self.http('POST', endpoint, {}, token=False)[0], 401)
            self.assertEqual(self.http('POST', endpoint, {}, headers={'Origin': 'https://elsewhere.invalid'})[0], 403)
            self.assertEqual(self.http('GET', endpoint)[0], 405)
            self.assertEqual(self.http('POST', endpoint, {'folder': str(self.before)})[0], 400)
            self.assertEqual(self.http('POST', endpoint + '?folder=other', {})[0], 400)
            chooser.assert_not_called()
            status, result, _ = self.http('POST', endpoint, {})
            self.assertEqual((status, result), (200, {'folder': str(picked)}))
            chooser.assert_called_once_with()
            chooser.return_value = None
            self.assertEqual(self.http('POST', endpoint, {})[:2], (200, {'folder': None}))

    def test_recents_persist_deduplicate_and_only_remember_actual_projects(self):
        chosen = [configured_project(self.root / f'game-{n}') for n in range(7)]
        endpoint = '/api/projects/choose'
        with mock.patch.object(app, 'choose_folder', side_effect=[*map(str, chosen), str(chosen[4]),
                                                                 str(self.root)]):
            for _ in range(8):
                self.assertEqual(self.http('POST', endpoint, {})[0], 200)
            self.assertEqual(self.http('POST', endpoint, {})[0], 400)
        path = '/api/projects/recent'
        self.assertEqual(self.http('GET', path, token=False)[0], 401)
        expected = [str(chosen[n]) for n in (4, 6, 5, 3, 2, 1)]
        self.assertEqual(self.http('GET', path)[:2], (200, {'folders': expected}))
        self.assertEqual(app.App(self.store, self.start).recent_projects(), expected)

    def test_field_checks_name_missing_project_missing_setup_and_different_layouts(self):
        before = configured_project(self.root / 'my-game-before')
        after = configured_project(self.root / 'my-game-after')
        endpoint = '/api/projects/check'
        with mock.patch.object(self.server.app, 'start') as worker:
            self.assertEqual(self.http('POST', endpoint, {'after': str(self.root)})[0], 200)
            result = self.http('POST', endpoint, {'after': str(self.root)})[1]
            self.assertIn('no project.godot', result['after']['problem'])
            config = after / 'expectrail.project.json'
            original = config.read_text()
            config.unlink()
            result = self.http('POST', endpoint, {'after': str(after)})[1]
            self.assertIn('review', result['after']['problem'])
            self.assertEqual(result['beforeSuggestion'], {'folder': str(before), 'source': 'sibling'})
            (after / 'entry.tscn').rename(after / 'other.tscn')
            config.write_text(original.replace('entry.tscn', 'other.tscn'))
            result = self.http('POST', endpoint, {'after': str(after), 'before': str(before)})[1]
            self.assertIsNone(result['before']['problem'])
            self.assertIn('different layouts', result['after']['problem'])
            self.assertIn('entry.tscn', result['after']['problem'])
            worker.assert_not_called()

    def test_implicit_sibling_cannot_escape_through_symlinks(self):
        after = configured_project(self.root / 'left' / 'game-after')
        unrelated = configured_project(self.root / 'other' / 'secret')
        sibling = after.parent / 'game-before'
        sibling.symlink_to(unrelated, target_is_directory=True)
        endpoint = '/api/projects/check'
        result = self.http('POST', endpoint, {'after': str(after)})[1]
        self.assertIsNone(result['beforeSuggestion'])
        self.assertNotIn(str(unrelated), str(result))
        sibling.unlink()
        sibling.mkdir()
        (sibling / 'project.godot').symlink_to(unrelated / 'project.godot')
        result = self.http('POST', endpoint, {'after': str(after)})[1]
        self.assertIsNone(result['beforeSuggestion'])

    @unittest.skipUnless(shutil.which('git'), 'Git is required for local project history')
    def test_worktree_and_previous_commit_use_the_same_project_subfolder(self):
        repo = self.root / 'source'
        after = configured_project(repo / 'game')
        git = ['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid']
        subprocess.run(git + ['init', '-q'], check=True)
        subprocess.run(git + ['add', '.'], check=True)
        subprocess.run(git + ['commit', '-qm', 'Before'], check=True)
        body = {'after': str(after)}
        code, problem, _ = self.http('POST', '/api/projects/previous', body)
        self.assertEqual(code, 400, problem)
        self.assertIn('Choose a Before folder', problem['detail'])
        before_tree = self.root / 'checked-out-before'
        subprocess.run(git + ['worktree', 'add', '-q', '--detach', str(before_tree)], check=True)
        (after / 'entry.tscn').write_text('Current version')
        subprocess.run(git + ['commit', '-qam', 'After'], check=True)
        foreign = configured_project(self.root / 'unrelated' / 'game')
        (foreign.parent / '.git').write_text(f'gitdir: {repo / ".git"}\n')
        foreign_body = {'after': str(foreign)}
        check = self.http('POST', '/api/projects/check', foreign_body)[1]
        self.assertFalse(check['hasGitCheckout'])
        self.assertIsNone(check['beforeSuggestion'])
        self.assertEqual(self.http('POST', '/api/projects/previous', foreign_body)[0], 400)
        result = self.http('POST', '/api/projects/check', body)[1]
        self.assertEqual(result['beforeSuggestion'], {'folder': str(before_tree / 'game'), 'source': 'worktree'})
        code, previous, _ = self.http('POST', '/api/projects/previous', body)
        self.assertEqual(code, 200, previous)
        before = Path(previous['folder'])
        self.assertEqual(previous['source'], 'previous-commit')
        self.assertEqual((before / 'entry.tscn').read_bytes(), (before_tree / 'game/entry.tscn').read_bytes())
        self.assertEqual((after / 'entry.tscn').read_text(), 'Current version')
        self.assertEqual(self.http('POST', '/api/projects/check', body | {'before': str(before)})[1]['before']['problem'],
                         None)
        status, job, _ = self.http('POST', '/api/jobs', body | {'before': str(before)})
        self.assertEqual(status, 201, job)
        self.assertEqual(self.http('GET', '/api/projects/recent')[1], {'folders': [str(after)]})
