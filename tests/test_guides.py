"""Keep the deployment guide on the merged two-job workflow, without deploying it."""
from html.parser import HTMLParser
from pathlib import Path
import unittest
from unittest import mock

import yaml
from tools import ci_checks
from tools import front_door as front


class Guide(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.in_example = self.in_policy = self.in_cell = False
        self.example, self.cells = '', []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'pre' and attrs.get('id') == 'action-example':
            self.in_example = True
        if tag == 'table' and attrs.get('id') == 'check-policy':
            self.in_policy = True
        if tag == 'td' and self.in_policy:
            self.in_cell = True
            self.cells.append('')

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.in_example = False
        if tag == 'table':
            self.in_policy = False
        if tag == 'td':
            self.in_cell = False

    def handle_data(self, text):
        if self.in_example:
            self.example += text
        if self.in_cell:
            self.cells[-1] += text


class GuidesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guide = Guide((front.ROOT / 'docs/guides.html').read_text())

    def test_published_caller_matches_the_merged_capture_caller(self):
        actual = yaml.safe_load((front.ROOT / '.github/workflows/expectrail-verify.yml').read_text())
        example = yaml.safe_load(self.guide.example)
        self.assertEqual(example, actual)
        self.assertEqual(example['jobs']['verify']['uses'], './.github/workflows/expectrail-capture.yml')
        self.assertEqual(example['permissions'], {'contents': 'read'})
        self.assertNotIn('secrets', example['jobs']['verify'])
        self.assertNotIn('steps', example['jobs']['verify'])

    def test_published_check_policy_uses_the_real_names_and_repository_exception(self):
        self.assertEqual(self.guide.cells, [
            ci_checks.CLEARANCE, 'Require from the dedicated App', 'Advisory; not required',
            ci_checks.EVIDENCE, 'Reporting; do not require as the verdict', 'Reporting',
        ])
        canonical = (front.ROOT / 'docs/ci-gate.md').read_text()
        general, own = canonical.split('## On Expectrail\'s own repository', 1)
        own = own.split('## Earlier composite actions', 1)[0]
        self.assertIn('Require only\n**' + ci_checks.CLEARANCE + '**', general)
        self.assertIn('dedicated App as its expected source', general)
        self.assertIn('**' + ci_checks.CLEARANCE + '** is advisory', own)
        self.assertIn('it is not a required check', own)

    def altered_problems(self, name, addition):
        original = Path.read_text
        path = front.ROOT / name
        def read(p, *args, **kwargs):
            text = original(p, *args, **kwargs)
            return text + addition if p == path else text
        with mock.patch.object(Path, 'read_text', read):
            return front.problems()

    def test_both_new_pages_are_in_the_ci_link_check(self):
        for name in ('docs/guides.html', 'docs/positioning.html'):
            with self.subTest(page=name):
                problems = self.altered_problems(name, '<a href="#missing-guide-anchor">broken</a>')
                self.assertTrue(any(name in p and 'missing anchor' in p for p in problems), problems)

    def test_both_new_pages_reject_a_command_with_no_ledger_entry(self):
        for name in ('docs/guides.html', 'docs/positioning.html'):
            with self.subTest(page=name):
                problems = self.altered_problems(name, '<code>python3 -m invented_guide_mode</code>')
                self.assertTrue(any('invented_guide_mode' in p for p in problems), problems)


if __name__ == '__main__':
    unittest.main()
