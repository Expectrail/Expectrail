"""`expectrail verify --project` refuses, before any replay, a project whose config can judge nothing (#260).

A configured project chooses its routes and its approved checks in `expectrail.project.json`. When the
base's config names no usable route, or no approved check, every replay would end "no checks ran". The
command says what to change instead, exits 5 (could not be carried out) and starts no job. No check is
approved here; a draft named in `approvedContracts` stays a draft.
"""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from expectrail import cli, project_config, project_job

REPO = Path(__file__).resolve().parents[1]
CRATE = REPO / 'tests/projects/crate-run'
APPROVED = REPO / 'agents/specs/player-stays-above-ground.json'


class UnreadyTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.game = self.root / 'game'
        shutil.copytree(CRATE / 'project', self.game)
        shutil.copytree(CRATE / 'routes', self.game / 'routes')
        (self.game / 'checks').mkdir()
        shutil.copyfile(APPROVED, self.game / 'checks/floor.json')
        shutil.copyfile(CRATE / 'specs/crate-stays-above-floor.json', self.game / 'checks/draft.json')
        self.jobs = self.root / 'jobs'

    def configure(self, **fields):
        path = self.game / project_config.FILENAME
        doc = json.loads(path.read_text(encoding='utf-8'))
        for key, value in fields.items():
            if value is None:
                doc.pop(key, None)
            else:
                doc[key] = value
        path.write_text(json.dumps(doc), encoding='utf-8')

    def verify(self, *extra):
        with redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()) as out:
            code = cli.main(['verify', '--project', str(self.game), *extra, '--jobs-root', str(self.jobs), '--json'])
        return code, err.getvalue(), out.getvalue()

    def test_a_config_with_a_route_and_an_approved_check_is_ready(self):
        self.configure(routes=['routes/walk.json'], approvedContracts=['checks/floor.json'])
        self.assertEqual(project_job.unready(self.game), [])

    def test_no_routes_and_no_checks_names_both_fields_and_starts_no_job(self):
        # The bundled game's shipped config is like this today: bindings, but no routes or checks.
        code, err, out = self.verify()
        self.assertEqual(code, 5, err)
        self.assertIn('Nothing here can be verified yet', err)
        self.assertIn('"routes"', err)
        self.assertIn('"approvedContracts"', err)
        self.assertIn('A person approves a check before it judges', err)
        self.assertNotIn('routes/*.json', err)   # the gate's internal folder is not the developer's
        self.assertEqual(out, '')
        self.assertFalse(self.jobs.exists())

    def test_routes_but_no_checks_names_only_the_checks(self):
        self.configure(routes=['routes/walk.json'])
        steps = project_job.unready(self.game)
        self.assertEqual(len(steps), 1, steps)
        self.assertIn('"approvedContracts"', steps[0])
        code, err, _ = self.verify()
        self.assertEqual(code, 5)
        self.assertFalse(self.jobs.exists())

    def test_checks_but_no_routes_names_only_the_routes(self):
        self.configure(approvedContracts=['checks/floor.json'])
        steps = project_job.unready(self.game)
        self.assertEqual(len(steps), 1, steps)
        self.assertIn('"routes"', steps[0])
        self.assertIn('expectrail route', steps[0])

    def test_a_named_draft_is_said_to_be_a_draft_and_is_never_approved_here(self):
        self.configure(routes=['routes/walk.json'], approvedContracts=['checks/draft.json'])
        before = (self.game / 'checks/draft.json').read_bytes()
        code, err, _ = self.verify()
        self.assertEqual(code, 5)
        self.assertIn('1 check named in "approvedContracts" is a draft nobody has approved', err)
        self.assertEqual((self.game / 'checks/draft.json').read_bytes(), before)
        self.assertFalse(self.jobs.exists())

    def test_one_approved_check_beside_a_draft_is_ready(self):
        self.configure(routes=['routes/walk.json'], approvedContracts=['checks/floor.json', 'checks/draft.json'])
        self.assertEqual(project_job.unready(self.game), [])

    def test_a_draft_config_from_init_also_says_it_is_a_draft(self):
        self.configure(routes=['routes/walk.json'], draft=True)
        steps = project_job.unready(self.game)
        self.assertEqual(len(steps), 2, steps)
        self.assertIn('"approvedContracts"', steps[0])
        self.assertIn('remove "draft"', steps[1])

    def test_a_draft_config_that_can_judge_is_left_to_the_gate(self):
        # The gate already keeps a draft config from an accept and still lets a failure reject.
        self.configure(routes=['routes/walk.json'], approvedContracts=['checks/floor.json'], draft=True)
        self.assertEqual(project_job.unready(self.game), [])

    def test_the_base_config_decides_not_the_head(self):
        self.configure(routes=['routes/walk.json'], approvedContracts=['checks/floor.json'])
        head = self.root / 'head'
        shutil.copytree(self.game, head)
        path = head / project_config.FILENAME
        doc = json.loads(path.read_text(encoding='utf-8'))
        doc.pop('approvedContracts')
        path.write_text(json.dumps(doc), encoding='utf-8')
        self.assertEqual(project_job.unready(self.game), [])
        self.assertNotEqual(project_job.unready(head), [])
        # Given as the base, the complete config is ready; the head's dropped check is the gate's
        # to report as a config that differs.
        with mock.patch.object(project_job, 'prepare', side_effect=SystemExit('prepared')):
            with self.assertRaisesRegex(SystemExit, 'prepared'):
                with redirect_stderr(io.StringIO()):
                    cli.main(['verify', '--project', str(head), '--base', str(self.game),
                              '--jobs-root', str(self.jobs), '--json'])

    def test_held_out_checks_are_not_refused_for_want_of_public_ones(self):
        with mock.patch.object(project_job, 'unready', side_effect=AssertionError('asked')), \
                mock.patch.object(project_job, 'prepare', side_effect=SystemExit('prepared')):
            with self.assertRaisesRegex(SystemExit, 'prepared'):
                with redirect_stderr(io.StringIO()):
                    cli.main(['verify', '--project', str(self.game), '--with-heldout',
                              '--jobs-root', str(self.jobs), '--json'])

    def test_an_unreadable_config_keeps_its_own_error(self):
        (self.game / project_config.FILENAME).write_text('not json', encoding='utf-8')
        code, err, _ = self.verify()
        self.assertEqual(code, 5)
        self.assertIn('Project config', err)
        self.assertNotIn('Nothing here can be verified yet', err)


if __name__ == '__main__':
    unittest.main()
