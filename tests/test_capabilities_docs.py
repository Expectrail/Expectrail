"""Every root doc is guarded, including installed command variants (#244)."""
import copy
from pathlib import Path
import tempfile
import unittest

from expectrail import capabilities as c


class DocumentationInventoryTest(unittest.TestCase):
    def test_new_doc_is_read_without_editing_a_static_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in (*c.ADVERTS, 'docs/new-mode.md'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('`expectrail teleport --project game`' if name.endswith('new-mode.md') else '')
            texts = c.read_adverts(root)
            self.assertIn('docs/new-mode.md', texts)
            errors = c.advert_problems(c.load(), texts, root)
            self.assertEqual(errors, [
                'docs/new-mode.md: public documentation page has no ledger row or explicit non-mode reason',
                'docs/new-mode.md: names the CLI mode expectrail teleport, which no ledger row lists'])

    def test_registering_a_page_does_not_hide_its_unlisted_command_or_switch(self):
        doc = copy.deepcopy(c.load())
        doc['notModes']['docs']['docs/new-mode.md'] = 'A protocol, not an executable mode.'
        errors = c.advert_problems(doc, {'docs/new-mode.md':
            'python3 -m expectrail.teleport with EXPECTRAIL_TELEPORT=1'})
        self.assertEqual(errors, [
            'docs/new-mode.md: names the command expectrail.teleport, which no ledger row lists',
            'docs/new-mode.md: names the switch EXPECTRAIL_TELEPORT, which no ledger row lists'])

    def test_cli_examples_cover_module_entry_flags_and_html_but_not_prose(self):
        text = '''The expectrail command is installed.
```sh
python3 -m expectrail.cli --jobs-root jobs ingest report.json \\
    --propose --repair
expectrail route --auto --out route.json
```
<code>expectrail verify --intent fix</code>
`expectrail verify --auto-fix`
'''
        self.assertEqual(c.cli_modes(text), {'expectrail ingest', 'expectrail ingest --propose',
            'expectrail ingest --repair', 'expectrail route', 'expectrail route --auto',
            'expectrail verify', 'expectrail verify --intent', 'expectrail verify --auto-fix'})

    def test_new_cli_variant_needs_its_own_row_ownership(self):
        doc = c.load()
        for row in doc['rows']:
            row['names'] = [n for n in row.get('names', []) if n != 'expectrail ingest --repair']
        self.assertEqual(c.advert_problems(doc, {'README.md': '`expectrail ingest report.json --repair`'}),
            ['README.md: names the CLI mode expectrail ingest --repair, which no ledger row lists'])

    def test_doc_and_docs_directory_symlinks_are_refused(self):
        for directory in (False, True):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp);target = root / 'target';target.mkdir()
                if directory:
                    (root / 'docs').symlink_to(target, target_is_directory=True)
                else:
                    (root / 'docs').mkdir()
                    (root / 'docs/aaa.md').symlink_to(target / 'never-read.md')
                    for name in c.ADVERTS:
                        (root / name).write_text('')
                with self.assertRaisesRegex(c.LedgerError, 'symlinks are refused'):
                    c.read_adverts(root)

    def test_ci_discovers_the_ledger_tests_without_workflow_edits(self):
        # Read only: the normal test job already invokes unittest discovery.
        workflow = (c.ROOT / '.github/workflows/ci.yml').read_text()
        self.assertIn('python -m unittest discover -s tests -t .', workflow)
        self.assertEqual(c.problems(c.load()), [])

    def test_roadmap_is_explicitly_unbuilt_and_no_new_row_is_measured(self):
        rows = {r['id']: r for r in c.load()['rows']}
        self.assertIn('not implemented or measured', rows['unsupported-roadmap']['limits'])
        for rid in ('public-reproduction', 'release-controls', 'capture-spike', 'unsupported-roadmap'):
            self.assertNotEqual(rows[rid]['status'], 'measured')
