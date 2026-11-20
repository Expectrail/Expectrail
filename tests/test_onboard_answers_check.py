"""Check simulated answers against the real review inputs without applying them.

Guard: test change intended (#332)
Reason: cover the read-only rehearsal entry point and its shared validation.
"""
import io
import json
import unittest
from unittest.mock import patch

from expectrail import cli
from tests import cli_capture
from tests import test_onboard_review


class AnswersCheckTest(unittest.TestCase):
    def fixture(self):
        fixture = test_onboard_review.HumanReviewTest()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        return fixture

    def check(self, answers):
        out = io.StringIO()
        with patch('expectrail.approval.approve', side_effect=AssertionError('writer called')):
            with cli_capture.command_output(out):
                result = cli.main(['onboard', '--check-answers', str(answers)])
        return result, out.getvalue()

    def test_a_simulated_decline_is_validated_without_touching_any_file(self):
        fixture = self.fixture()
        answers = fixture.answers(objects={'player': False}, checks={'throwaway-review-only': False})

        def snapshot():
            return {p.relative_to(fixture.tmp): p.read_bytes()
                    for p in fixture.tmp.rglob('*') if p.is_file()}

        before = snapshot()
        result, output = self.check(answers)
        self.assertEqual(result, 0, output)
        self.assertEqual(json.loads(output), {'selectedChecks': [],
                                             'allObjectsConfirmed': False, 'applied': False})
        self.assertEqual(snapshot(), before)

    def test_an_invented_check_can_be_selected_without_calling_the_writer(self):
        fixture = self.fixture()
        before = fixture.spec_path.read_bytes()
        result, output = self.check(fixture.answers())
        self.assertEqual(result, 0, output)
        self.assertEqual(json.loads(output), {'selectedChecks': ['throwaway-review-only'],
                                             'allObjectsConfirmed': True, 'applied': False})
        self.assertEqual(fixture.spec_path.read_bytes(), before)

    def test_page_output_names_the_missing_parent_and_leaves_it_absent(self):
        fixture = self.fixture()
        dest = fixture.tmp / 'missing' / 'review.html'
        out = io.StringIO()
        with cli_capture.command_output(out):
            result = cli.main(['onboard', '--project', str(fixture.root), '--out', str(dest)])
        self.assertEqual(result, 5)
        self.assertIn(f'Create the --out directory {dest.parent}', out.getvalue())
        self.assertFalse(dest.parent.exists())

    def test_missing_answers_file_names_how_to_recover(self):
        fixture = self.fixture()
        code, message = self.check(fixture.tmp / 'missing-answers.json')
        self.assertEqual(code, 5)
        self.assertIn('Check the answers file path or save a fresh file', message)

    def test_changed_review_refuses_before_any_write(self):
        fixture = self.fixture()
        answers = fixture.answers(objects={'player': False}, checks={'throwaway-review-only': False})
        fixture.manifest.write_bytes(fixture.manifest.read_bytes() + b' ')
        original = fixture.spec_path.read_bytes()
        out = io.StringIO()
        with cli_capture.command_output(out):
            result = cli.main(['onboard', '--check-answers', str(answers)])
        self.assertEqual(result, 5)
        self.assertIn('create a new review page', out.getvalue())
        self.assertEqual(fixture.spec_path.read_bytes(), original)
