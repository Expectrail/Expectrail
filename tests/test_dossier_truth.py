"""Truth pass: fail closed on unreferenced figures, source drift and denominator inflation."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from tools import dossier as d
from tools.dossier_figures import Figures, changes

ROOT = Path(__file__).resolve().parents[1]
COMMIT = '7d61695f77534c175a57934ca06cb73b55c7417c'


class DossierTruthTest(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name in d.INPUTS:
            path = root/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,path)
        return root

    def test_generator_refuses_a_figure_without_its_source_even_when_other_sections_are_cited(self):
        with mock.patch.object(d,'spend_section',return_value='<h2>Spend</h2><p>999 requests</p>'):
            with self.assertRaisesRegex(d.EvidenceError,'figure has no source reference.*999 requests'):
                d.build(ROOT,COMMIT)
        audit=Figures('<p><a href="sources/not-allowlisted.json">999</a></p>',d.local_sources())
        self.assertEqual(audit.missing,['999'])
        self.assertEqual(Figures('<p><a href="https://example.invalid">999</a></p>').missing,['999'])

    def test_latest_main_gate_counts_come_from_the_saved_artifact_and_job(self):
        source=d.sources(ROOT,COMMIT);text=d.current_release_gate(source,source[d.LEDGER].json())
        for count in ('25 / 35','10 / 35','0 / 35'):
            self.assertIn(count,text)
        meta=source[d.CI_META].json()
        self.assertIn(meta['run']['url']+'/job/'+str(meta['jobs'][0]['id']),text)
        self.assertIn('68',text)
        self.assertEqual(json.loads((ROOT/d.GATE_JSON).read_text())['commit'],meta['run']['head_sha'])

    def test_bad_main_identity_and_changed_artifact_records_are_stops(self):
        for field,value in (('head_branch','another-branch'),('event','pull_request')):
            root=self.fixture();p=root/d.CI_META;data=json.loads(p.read_text());data['run'][field]=value;p.write_text(json.dumps(data))
            with self.subTest(field=field),self.assertRaisesRegex(d.EvidenceError,'not main CI'):
                d.build(root,COMMIT)
        root=self.fixture();p=root/d.GATE_JSON;data=json.loads(p.read_text());data['counts']['held']+=1;p.write_text(json.dumps(data))
        with self.assertRaisesRegex(d.EvidenceError,'summary disagrees'):
            d.build(root,COMMIT)

    def test_new_sources_do_not_silently_overrule_a_stale_ledger(self):
        root=self.fixture();p=root/d.LEDGER;data=json.loads(p.read_text())
        next(r for r in data['rows'] if r['id']=='outside-projects')['limits']+=' Dodge has a draft check awaiting approval.'
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(d.EvidenceError,'still calls approved Dodge check a draft'):
            d.build(root,COMMIT)

    def test_fresh_playtester_reach_and_clean_denominators_are_separate(self):
        src=d.sources(ROOT,COMMIT);text=d.playtest_section(src,src[d.LEDGER].json())
        for value in ('3 / 24','21 / 24','0 / 400','0 / 200'):
            self.assertIn(value,text)
        self.assertIn('same evaluation seeds',text)
        self.assertNotIn('0 / 600',text)
        root=self.fixture();p=root/d.PLAYTEST_REACH;p.write_text(p.read_text().replace('0/200 fresh improved.','0/400 fresh improved.'))
        with self.assertRaisesRegex(d.EvidenceError,'denominators disagree'):
            d.build(root,COMMIT)

    def test_ci_playtest_proof_requires_all_three_actual_pass_lines(self):
        root=self.fixture();p=root/d.PLAYTEST_CI;data=json.loads(p.read_text());data['lines'].pop();p.write_text(json.dumps(data))
        with self.assertRaisesRegex(d.EvidenceError,'test results missing'):
            d.build(root,COMMIT)

    def test_untuned_sensor_rate_and_transfer_failure_stay_advisory(self):
        src=d.sources(ROOT,COMMIT);text=d.template_section(src,src[d.LEDGER].json())
        for value in ('8 / 341','2.35%','540 / 540','100%','counts toward no verdict'):
            self.assertIn(value,text)
        root=self.fixture();p=root/d.TEMPLATE;p.write_text(p.read_text().replace('**2.35%**','**1.35%**'))
        with self.assertRaisesRegex(d.EvidenceError,'rate/denominator disagree'):
            d.build(root,COMMIT)

    def test_failed_onboarding_is_needs_review_not_seeded_bug_detection(self):
        source=d.sources(ROOT,COMMIT);text=d.outside_updates(source,source[d.LEDGER].json())
        self.assertIn('System Override: onboarding failed',text)
        self.assertIn('Breakout: onboarding failed',text)
        self.assertIn('3 / 3',text)
        self.assertIn('not approved checks or seeded-bug detection',text)
        root=self.fixture();p=root/d.BREAKOUT;p.write_text(p.read_text().replace('"decision": "needs-review"','"decision": "accept"',1))
        with self.assertRaisesRegex(d.EvidenceError,'differs from verbatim handover cache'):
            d.build(root,COMMIT)

    def test_request_holds_are_read_from_code_and_not_presented_as_fixer_bill_caps(self):
        source=d.sources(ROOT,COMMIT);text=d.spend_section(source,source[d.LEDGER].json())
        for value in ('$0.0025 / image','$0.05 / request','$1 / invocation','$200','does not bound the cost inside one fixer invocation'):
            self.assertIn(value,text)
        self.assertEqual(Figures(text,d.local_sources()).missing,[])

    def test_frozen_ledger_output_matches_the_current_claims(self):
        root=self.fixture();out=root/'index.html'
        self.assertEqual(d.main(['--root',str(root),'--out',str(out),'--commit',COMMIT]),0)
        snapshot=root/'sources/capabilities.json'
        self.assertEqual(snapshot.read_bytes(),(root/d.LEDGER).read_bytes())
        snapshot.write_text('{}')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(d.main(['--root',str(root),'--out',str(out),'--check']),2)

    def test_homepage_summary_is_derived_and_mismatched_summary_is_detected(self):
        text=d.homepage_summary(ROOT,COMMIT)
        for value in ('25 / 35','10 / 35','3 / 24','0 / 400','0 / 200','8 / 341','2.35%'):
            self.assertIn(value,text)
        wrapped='before<!-- dossier-summary:start -->old<!-- dossier-summary:end -->after'
        rendered=d.with_homepage_summary(wrapped,text)
        self.assertIn(text,rendered)
        self.assertNotIn('>old<',rendered)
        self.assertEqual(d.with_homepage_summary(rendered,text),rendered)
        self.assertEqual(Figures(text).missing,[])

    def test_numeric_diff_retains_occurrence_counts_and_actual_source_references(self):
        url='https://github.com/Expectrail/Expectrail/actions/runs/43814718684'
        old=f'<h2 id="gate">Gate</h2><a href="{url}">18 / 35</a><a href="{url}">18 / 35</a>'
        new=f'<h2 id="gate">Gate</h2><a href="{url}">25 / 35</a>'
        diff=changes(old,new)
        self.assertEqual(diff['removed'][0]['figure'],'18 / 35')
        self.assertEqual(diff['removed'][0]['occurrences'],2)
        self.assertEqual(diff['added'][0]['figure'],'25 / 35')
        self.assertEqual(diff['added'][0]['sources'],[url])


    def test_all_retained_homepage_counters_bars_and_cost_match_the_ledger(self):
        text=(ROOT/'docs/index.html').read_text();ledger=json.loads((ROOT/d.LEDGER).read_text())
        d.check_homepage_figures(text,ledger)
        for old,new in (('<b>0 of 7</b>','<b>1 of 7</b>'),('data-count="8">8</span> of 8','data-count="9">9</span> of 8')):
            changed=text.replace(old,new,1)
            self.assertNotEqual(changed,text)
            with self.subTest(old=old),self.assertRaisesRegex(d.EvidenceError,'disagree with ledger'):
                d.check_homepage_figures(changed,ledger)
