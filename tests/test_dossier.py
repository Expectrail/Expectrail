"""The release dossier is derived offline, with provenance on every visible figure."""
from html.parser import HTMLParser
import contextlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools import dossier as d

ROOT=Path(__file__).resolve().parents[1]
PAGE=ROOT/'docs/release/index.html'


class Figures(HTMLParser):
    def __init__(self,text):
        super().__init__(convert_charrefs=True)
        self.stack=[];self.missing=[];self.linked=[]
        self.feed(text)

    def handle_starttag(self,tag,attrs):
        if tag not in {'meta','link','br','hr','img','input'}:
            self.stack.append((tag,dict(attrs).get('href')))

    def handle_endtag(self,tag):
        for n in range(len(self.stack)-1,-1,-1):
            if self.stack[n][0]==tag:
                del self.stack[n:]
                break

    def handle_data(self,text):
        if any(t in {'style','script'} for t,_ in self.stack) or not re.search(r'\d',text):
            return
        href=next((u for t,u in reversed(self.stack) if t=='a'),None)
        valid=href and (re.match(r'https://github\.com/Expectrail/Expectrail/(?:blob/|actions/runs/|issues/|commit/|tree/|pull/)',href) or href in d.local_sources())
        (self.linked if valid else self.missing).append(text)


class DossierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.commit=re.search(r'data-source-commit="([a-f0-9]{40})"',PAGE.read_text())[1]

    def fixture(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        for name in d.INPUTS:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,path)
        return root

    def test_generation_is_deterministic_and_the_checked_in_page_is_a_cited_snapshot(self):
        # The page is a release snapshot that names its source commit; it is not required to track
        # every later edit of its sources, or each such edit would fail unrelated pull requests.
        # Staleness is checked when a release is cut: `python -m tools.dossier --check`.
        first=d.build(ROOT,self.commit)
        self.assertEqual(first,d.build(ROOT,self.commit))
        page=PAGE.read_text()
        self.assertRegex(page,r'data-source-commit="[0-9a-f]{40}"')
        audit=Figures(page)
        self.assertGreater(len(audit.linked),100)
        self.assertEqual(audit.missing,[])

    def test_every_visible_figure_has_a_source_link_and_the_audit_catches_missing_links(self):
        text=d.build(ROOT,self.commit)
        audit=Figures(text)
        self.assertGreater(len(audit.linked),100)
        self.assertEqual(audit.missing,[])
        self.assertEqual(Figures(text.replace('</main>','<p>999 unsupported cases</p></main>')).missing,['999 unsupported cases'])
        self.assertEqual(Figures('<a href="https://example.invalid">99</a>').missing,['99'])

    def test_cli_generates_offline_with_network_and_child_process_creation_disabled(self):
        root=self.fixture();out=root/'output.html'
        code='''import sys
sys.path.insert(0,sys.argv[1])
def deny(event,args):
    if event.startswith(('socket.','urllib.')) or event=='subprocess.Popen':
        raise AssertionError('external activity: '+event)
sys.addaudithook(deny)
from tools import dossier
raise SystemExit(dossier.main(['--root',sys.argv[2],'--out',sys.argv[3],'--commit',sys.argv[4]]))
'''
        got=subprocess.run([sys.executable,'-I','-c',code,str(ROOT),str(root),str(out),self.commit],capture_output=True,text=True)
        self.assertEqual(got.returncode,0,got.stdout+got.stderr)
        self.assertEqual(out.read_text(),d.build(root,self.commit))

    def test_only_the_explicit_public_inputs_are_read_and_no_links_are_followed(self):
        original=Path.read_text;opened=[]
        def read(path,*args,**kwargs):
            name=path.relative_to(ROOT).as_posix()
            self.assertIn(name,d.INPUTS)
            opened.append(name)
            return original(path,*args,**kwargs)
        with mock.patch.object(Path,'read_text',read):
            d.build(ROOT,self.commit)
        self.assertEqual(opened,list(d.INPUTS))
        self.assertFalse(any('blind-' in p or any(part.startswith('fresh-') for part in Path(p).parts) for p in opened))

    def test_symlinked_evidence_is_refused_before_reading_its_target(self):
        root=self.fixture();path=root/d.PUBLIC
        target=root/'unrelated.txt';target.write_text('not evidence')
        path.unlink();path.symlink_to(target)
        with self.assertRaisesRegex(d.EvidenceError,'links are refused'):
            d.build(root,self.commit)

    def test_missing_evidence_never_overwrites_a_previous_dossier(self):
        root=self.fixture();(root/d.GATE).unlink()
        out=root/'old.html';out.write_text('previous dossier')
        with contextlib.redirect_stderr(io.StringIO()):
            status=d.main(['--root',str(root),'--out',str(out),'--commit',self.commit])
        self.assertEqual(status,2)
        self.assertEqual(out.read_text(),'previous dossier')

    def test_an_unpublished_sample_is_shown_as_not_recorded_and_never_counted(self):
        root=self.fixture();p=root/d.SAMPLES;doc=json.loads(p.read_text())
        unpublished=[s for s in doc['samples'] if s.get('repairRecorded') is False]
        self.assertTrue(unpublished)   # the recorded-fix sample, until a live repair is recorded
        text=d.build(root,self.commit)
        self.assertIn('not recorded yet',text)
        for s in unpublished: s['repairRecorded']=True
        p.write_text(json.dumps(doc))
        with self.assertRaisesRegex(d.EvidenceError,'missing or ambiguous recorded result'):
            d.build(root,self.commit)

    def test_inconsistent_reproduction_totals_are_refused(self):
        root=self.fixture();p=root/d.PUBLIC
        text=p.read_text();text=text.replace('"reproduced": 17','"reproduced": 18',1);p.write_text(text)
        with self.assertRaisesRegex(d.EvidenceError,'counts disagree'):
            d.build(root,self.commit)

    def test_release_summary_cannot_promote_an_open_control_without_its_record(self):
        root=self.fixture();p=root/d.GATE
        text=p.read_text();m=re.search(r'Held (\d+), open (\d+)',text)
        self.assertIsNotNone(m)   # the edit below must change something, whatever main's counts are
        held,open_=int(m[1]),int(m[2])
        p.write_text(text.replace(m[0],f'Held {held+1}, open {open_-1}',1))
        with self.assertRaisesRegex(d.EvidenceError,'summary disagrees'):
            d.build(root,self.commit)

    def test_outcomes_are_counted_from_evidence_not_the_expected_sample_verdict(self):
        root=self.fixture();p=root/d.LEDGER;doc=json.loads(p.read_text())
        row=next(r for r in doc['rows'] if r['id']=='run-it')
        ev=next(e for e in row['evidence'] if 'sample clean:' in e['shows'] and 'vision questions answered' in e['shows'])
        ev['shows']=ev['shows'].replace('decided accept,','decided reject,')
        p.write_text(json.dumps(doc))
        rendered=d.build(root,self.commit).split('<h2 id="samples">',1)[1].split('<h2 id="runtime">',1)[0]
        self.assertRegex(rendered,r'>1 / 2</a>')
        self.assertRegex(rendered,r'>0 / 3</a>')

    def test_needs_review_is_neither_a_false_accept_nor_a_false_reject(self):
        cases=[{'actual':'accept','truth':'bad'},{'actual':'reject','truth':'good'},
               {'actual':'needs-review','truth':'bad'},{'actual':'needs-review','truth':'good'}]
        self.assertEqual(d.verdict_stats(cases),{'false_accept':1,'bad':2,'false_reject':1,'good':2,'review':2,'total':4})
        with self.assertRaises(d.EvidenceError):
            d.verdict_stats([])

    def test_singletons_do_not_become_runtime_percentiles_and_repeated_records_do(self):
        self.assertIsNone(d.percentiles([33.1]))
        self.assertIsNone(d.percentiles([]))
        self.assertEqual(d.percentiles([3,1,2]),(2,3))
        with self.assertRaises(d.EvidenceError):
            d.percentiles([float('nan')])
        root=self.fixture();p=root/d.LEDGER;doc=json.loads(p.read_text())
        doc['timings'].append(doc['timings'][0].copy());p.write_text(json.dumps(doc))
        with self.assertRaisesRegex(d.EvidenceError,'duplicate timing run'):
            d.build(root,self.commit)

    def test_check_uses_the_recorded_commit_and_detects_stale_output(self):
        root=self.fixture();out=root/'page.html';out.write_text(d.build(root,self.commit))
        snapshot=root/'sources/capabilities.json';snapshot.parent.mkdir();snapshot.write_text((root/d.LEDGER).read_text())
        with mock.patch.object(subprocess,'check_output',side_effect=AssertionError('check must use recorded source commit')),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.main(['--root',str(root),'--out',str(out),'--check']),0)
        out.write_text(out.read_text().replace('Generated from recorded public evidence','Edited without regeneration'))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(d.main(['--root',str(root),'--out',str(out),'--check']),2)


if __name__=='__main__':
    unittest.main()
