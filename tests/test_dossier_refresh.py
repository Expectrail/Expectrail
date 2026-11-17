"""Post-review records remain offline, derived and bounded (#268)."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools import dossier as d
from tools.dossier_figures import Figures

ROOT = Path(__file__).resolve().parents[1]
COMMIT = '21fde1b4be9362d209852e3d44221d059d110643'


class DossierRefreshTest(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name in d.INPUTS:
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, path)
        return root

    def test_all_post_review_merges_and_limits_are_cited(self):
        ss = d.sources(ROOT, COMMIT); text = d.post_review_updates(ss)
        for number in (573, 582, 583, 585, 586):
            self.assertIn(d.GH + '/pull/' + str(number), text)
        for limitation in ('candidate-withheld reproduction remain unmeasured',
                           'Menu reach is still missing', 'required mode still fails',
                           'workflow and deployed smoke were not run', 'no verdict contribution'):
            self.assertIn(limitation, text)
        self.assertEqual(Figures(text, d.local_sources()).missing, [])

    def test_frozen_closeout_uses_separate_denominators_and_preserves_unknowns(self):
        ss = d.sources(ROOT, COMMIT); text = d.frozen_template_closeout(ss)
        for value in ('118 / 120', '113 / 115', '110 / 112', '223 / 227', '4 / 227'):
            self.assertIn(value, text)
        self.assertIn('unknown, never a pass', text)
        self.assertIn('no cross-game transfer', text)
        original = d.template_section(ss, ss[d.LEDGER].json())
        self.assertIn('8 / 341', original)
        self.assertIn('2.35%', original)

    def test_frozen_frame_summary_and_plan_drift_are_errors(self):
        for change in ('summary', 'frame', 'plan', 'scope', 'proof'):
            root = self.fixture(); path = root / d.CLOSEOUT
            doc = json.loads(path.read_text())
            if change == 'summary': doc['summary']['pooledClean']['newPixels']['alarms'] = 0
            if change == 'frame': doc['runs'][0]['frames'][0]['status'] = 'not-found'
            if change == 'plan': (root / d.CLOSEOUT_PLAN).write_text('{}')
            if change == 'scope': doc['scope']['defaultVerdictChanged'] = True
            if change == 'proof': doc['pixelOnlyProof']['entireTraceRowsIdentical'] = False
            path.write_text(json.dumps(doc))
            with self.subTest(change=change), self.assertRaises(d.EvidenceError):
                d.build(root, COMMIT)

    def test_recovered_run_file_digest_is_checked_before_reporting_counts(self):
        root = self.fixture(); path = root / (d.RECOVERED + d.RECOVERY_FILES[0])
        path.write_text(path.read_text() + '\n')
        with self.assertRaisesRegex(d.EvidenceError, 'recovered file digest differs'):
            d.build(root, COMMIT)

    def test_recovered_totals_must_match_publication_even_if_inventory_hash_changes(self):
        root = self.fixture(); path = root / d.RECOVERY_SCORE
        doc = json.loads(path.read_text()); doc['totals']['reproduced'] += 1
        path.write_text(json.dumps(doc))
        meta_path = root / d.RECOVERY_META; meta = json.loads(meta_path.read_text())
        meta['files']['repro-score/repro-score.json'] = hashlib.sha256(path.read_bytes()).hexdigest()
        meta_path.write_text(json.dumps(meta))
        with self.assertRaisesRegex(d.EvidenceError, 'totals disagree with publication'):
            d.build(root, COMMIT)

    def test_generator_loads_and_builds_without_numpy_or_pil_or_network(self):
        code = '''import sys
sys.path.insert(0,sys.argv[1])
class Missing:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'numpy','PIL'}:
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0,Missing())
def deny(event,args):
    if event.startswith(('socket.','urllib.')) or event=='subprocess.Popen':
        raise AssertionError('external activity: '+event)
sys.addaudithook(deny)
from expectrail import capabilities
from tools import dossier
assert not capabilities.problems(capabilities.load())
assert dossier.build(dossier.ROOT,sys.argv[2])
'''
        got = subprocess.run([sys.executable, '-I', '-c', code, str(ROOT), COMMIT],
                             capture_output=True, text=True)
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)

    def test_checked_in_outputs_regenerate_from_recorded_sources(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main(['--check']), 0)
