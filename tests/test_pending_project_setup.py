"""A pending init draft tells the configured verifier which setup step is still open."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import shutil
import tempfile
import unittest

from expectrail import cli, onboard, project_config, project_job
from expectrail.orchestrator.request import RequestError

CRATE = Path(__file__).resolve().parents[1] / 'tests/projects/crate-run/project'


class PendingSetupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.game = self.root / 'game'
        shutil.copytree(CRATE, self.game, ignore=shutil.ignore_patterns(project_config.FILENAME))
        self.pending = self.game / onboard.PENDING

    def initialize(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['init', '--project', str(self.game)]), 0)
        self.assertTrue(self.pending.is_file())

    def test_verify_after_init_names_check_folders_and_image_field_without_writing(self):
        self.initialize()
        def snapshot():
            return {p.relative_to(self.game): p.read_bytes() for p in self.game.rglob('*') if p.is_file()}
        before = snapshot()
        jobs = self.root / 'jobs'
        with redirect_stderr(io.StringIO()) as err:
            result = cli.main(['verify', '--project', str(self.game), '--jobs-root', str(jobs), '--json'])
        self.assertEqual(result, 5)
        self.assertIn('choose Check folders to review ' + onboard.PENDING, err.getvalue())
        self.assertNotIn('expectrail onboard', err.getvalue())
        self.assertIn('bindings.player.texture', err.getvalue())
        self.assertNotIn('expectrail init', err.getvalue())
        self.assertEqual(snapshot(), before)
        self.assertFalse(jobs.exists())

    def test_missing_player_choice_points_to_binding_review(self):
        scene = self.game / 'main.tscn'
        scene.write_text(scene.read_text().replace('"Player"', '"Box"') +
                         '\n[node name="Ball" type="CharacterBody2D" parent="."]\n')
        self.initialize()
        with self.assertRaises(RequestError) as caught:
            project_job.read_config(self.game)
        self.assertIn('unresolvedBindings', str(caught.exception))
        self.assertIn(onboard.PENDING, str(caught.exception))
        self.assertNotIn('bindings.player.texture', str(caught.exception))

    def test_new_game_and_invalid_active_config_keep_the_original_error(self):
        with self.assertRaisesRegex(RequestError, 'Use expectrail init'):
            project_job.read_config(self.game)
        self.initialize()
        (self.game / project_config.FILENAME).write_text('invalid json')
        with self.assertRaises(RequestError) as caught:
            project_job.read_config(self.game)
        self.assertNotIn(onboard.PENDING, str(caught.exception))
        self.assertIn('Use expectrail init', str(caught.exception))

    def test_malformed_and_linked_drafts_do_not_supply_binding_guidance(self):
        self.initialize()
        saved = self.root / 'elsewhere.json'
        self.pending.rename(saved)
        self.pending.symlink_to(saved)
        for kind in ('link', 'malformed', 'wrong shape'):
            with self.subTest(kind=kind):
                if kind != 'link':
                    self.pending.unlink()
                    self.pending.write_text('bad json' if kind == 'malformed' else '[]')
                with self.assertRaises(RequestError) as caught:
                    project_job.read_config(self.game)
                self.assertNotIn('choose Check folders', str(caught.exception))
                self.assertNotIn('bindings.player.texture', str(caught.exception))
