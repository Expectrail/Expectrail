"""The bundled first-user trial uses the app's normal configured-folder path."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from expectrail import project_job
from expectrail.orchestrator import sample


class TrialFoldersTest(unittest.TestCase):
    def test_trial_folders_select_the_bundled_route_and_check_on_both_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'Trial folders'
            args = [sys.executable, '-m', 'tools.prepare_app_trial', str(destination)]
            run = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            original = sample.ROOT / sample.GAME / 'player/player.tscn'
            for name in ('Clean', 'Broken'):
                project = destination / name
                inspected = project_job.inspect(project)
                self.assertEqual(inspected['readinessSteps'], [])
                self.assertEqual(inspected['routeNames'], ['smoke'])
                self.assertEqual(inspected['checkNames'], ['player-stays-above-ground'])
                config = json.loads((project / 'expectrail.project.json').read_bytes())
                route, = config['routes']
                check, = config['approvedContracts']
                self.assertEqual((project / route).read_bytes(), (sample.ROOT / sample.ROUTE).read_bytes())
                self.assertEqual((project / check).read_bytes(),
                                 (sample.ROOT / sample.SPECS / 'player-stays-above-ground.json').read_bytes())
                scene = (project / 'player/player.tscn').read_bytes()
                if name == 'Clean':
                    self.assertEqual(scene, original.read_bytes())
                else:
                    self.assertNotEqual(scene, original.read_bytes())
                    self.assertIn(b'collision_mask = 14', scene)
            marker = destination / 'Clean' / 'my notes.txt'
            marker.write_text('keep')
            again = subprocess.run(args, capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            self.assertIn('new folder', again.stderr)
            self.assertEqual(marker.read_text(), 'keep')

    def test_existing_folder_link_cannot_redirect_preparation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'elsewhere'
            link = root / 'Trial'
            link.symlink_to(target, target_is_directory=True)
            run = subprocess.run([sys.executable, '-m', 'tools.prepare_app_trial', str(link)],
                                 capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse(target.exists())
