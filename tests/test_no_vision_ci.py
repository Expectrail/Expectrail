"""CI must see engine checks and sandbox records, not just needs-review. All replays are stand-ins."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from expectrail.orchestrator import engines, sample, store
from tests.test_ci_gate import INSIDE
from tests.test_two_observers import Game


class NoVisionCITest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.jobs = store.JobStore(Path(tmp.name) / 'jobs')
        game = Game()
        clean = (sample.ROOT / sample.GAME / 'player/player.tscn').read_bytes()
        game.look_of = lambda path: 'clean' if (path / 'player/player.tscn').read_bytes() == clean else 'BUG'

        def replay(*args):
            return dict(game.replay(*args), isolation=INSIDE)

        with mock.patch.dict(os.environ, {'MODEL_API_KEY': '', 'EXPECTRAIL_SAM_USD_CAP': ''}), \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('live call')), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.results = sample.run(self.jobs, engines={'godot': engines.GodotGate(replay=replay)})

    def test_sample_and_single_job_check_the_saved_evidence(self):
        from tools.check_no_vision import check

        check(self.results, self.jobs.root, sample=True)
        check(self.results[0]['status'], self.jobs.root, sample=False)
        self.assertEqual([r['status']['decision'] for r in self.results], ['needs-review', 'reject', 'needs-review'])

    def test_changed_verdict_missing_diagnostic_no_output_or_unsandboxed_replay_is_refused(self):
        from tools.check_no_vision import check

        status_path = self.jobs.paths(self.results[0]['status']['id']).status
        for field, value in (('decision', 'accept'), ('phase', 'failed'), ('diagnostics', []), ('output', None)):
            with self.subTest(field=field):
                doc = copy.deepcopy(self.results)
                doc[0]['status'][field] = value
                status_path.write_text(json.dumps(doc[0]['status']))
                with self.assertRaises((AssertionError, store.StoreError)):
                    check(doc, self.jobs.root, sample=True)
        status_path.write_text(json.dumps(self.results[0]['status']))
        path = self.jobs.paths(self.results[1]['status']['id']).output / 'findings.json'
        original = json.loads(path.read_text())
        for count in (0, original['isolation']['replays'] - 1):
            with self.subTest(sandboxed=count):
                doc = copy.deepcopy(original)
                doc['isolation'].update(sandboxed=count, sandbox=None if not count else doc['isolation']['sandbox'])
                doc['isolation']['reasons'] = ['stand-in replay outside the sandbox']
                path.write_text(json.dumps(doc))
                with self.assertRaises(AssertionError):
                    check(self.results, self.jobs.root, sample=True)
