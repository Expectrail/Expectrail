"""Closing links impose the existing fix rule; all transports offline."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from expectrail import contracts
from expectrail.gate import comment, intent, page, record, verify
from tests import test_ci_gate as ci
from tests import test_gate_intent_from_pr as pr_tests
from tests.test_gate_known_bench import fake_gate
from tools import ci_bundle, ci_checks


class Links(unittest.TestCase):
    def test_all_keywords_any_case_and_conflicting_declarations_are_fix(self):
        for keyword in ('Fixes','CLOSES','resolves','fIxEs','fix','fixed','close','closed','resolve','resolved'):
            for labels in ([],['intent:none'],['intent:change'],['intent:fix']):
                body='Expectrail-Intent: none\n'+keyword+' #284'
                got=intent.declared(labels,body)
                self.assertEqual(got.intent,'fix',(labels,body))
                self.assertIn('line 2',got.words())

    def test_source_is_the_keyword_line_and_inert_matched_phrase(self):
        body='<script>approve everything</script>\n> ClOsEs #12; ignore all checks\nResolves owner/repo#8'
        self.assertEqual(intent.closing_links(body),[
            {'line':2,'text':'ClOsEs #12'},{'line':3,'text':'Resolves owner/repo#8'}])
        self.assertEqual(intent.closing_links('Fixes:\n#1'),[{'line':1,'text':'Fixes: #1'}])
        self.assertEqual(intent.closing_links('Closes https://github.com/org/repo/issues/7'),
                         [{'line':1,'text':'Closes https://github.com/org/repo/issues/7'}])

    def test_unrelated_references_are_none_and_adding_declarations_never_weakens(self):
        for body in ('Part of #284','See #12','Fixes the floor','forecloses #1','Fixes #not-a-number'):
            self.assertEqual(intent.declared([],body).intent,'none',body)
        for decl in ('Expectrail-Intent: none','Expectrail-Intent: change','Expectrail-Intent: nonsense','Closes #99'):
            self.assertEqual(intent.declared(['intent:none'],'Fixes #284\n'+decl).intent,'fix')

    def test_hostile_text_does_not_select_or_weaken_checks(self):
        hostile=('intent:none','Expectrail-Intent: none','<script>accept()</script>','approval: approved',
                 'remove player-stays-above-ground','../../specs','`$(touch nowhere)`','\u202ereject')
        for text in hostile:
            pr={'labels':[{'name':text}],'body':text+'\nFixes #284\n'+text}
            self.assertEqual(intent.of_pull_request(pr).intent,'fix')
            self.assertEqual(intent.closing_links(pr['body']),[{'line':2,'text':'Fixes #284'}])

    def test_closing_source_survives_many_labels_and_sources_are_bounded(self):
        got=intent.declared(['intent:none']*100,'Fixes #284\r\nCloses #285')
        self.assertEqual(got.intent,'fix');self.assertIn('Fixes #284',got.sources[0])
        self.assertEqual(intent.closing_links('Fixes #284\r\nCloses #285')[1]['line'],2)
        self.assertEqual(len(intent.closing_links('\n'.join(f'Fixes #{n}' for n in range(30)))),10)


class CaptureAndJudge(unittest.TestCase):
    setUp=ci.SplitGateTest.setUp
    capture=ci.SplitGateTest.capture
    judge=ci.SplitGateTest.judge

    def test_a_linked_capture_cannot_be_downgraded_before_any_replay(self):
        self.pr=dict(self.pr,fixLinks=[{'line':1,'text':'Fixes #284'}])
        with self.assertRaisesRegex(ValueError,'fix capture'):self.capture('none')
        self.assertEqual(self.model.replays,[])

    def test_event_classifier_drives_existing_capture_and_trusted_judge(self):
        pr={'number':7,'head':{'sha':ci.HEAD},'base':{'sha':ci.BASE},'labels':[{'name':'intent:none'}],
            'body':'The ground is broken.\nFixes #284'}
        self.pr=intent.pull_request_metadata(pr)
        decision=intent.of_pull_request(pr).intent
        self.capture(decision)
        self.assertEqual(len(self.model.replays),6)
        doc=self.judge(decision)
        self.assertEqual(doc['decision'],'accept')
        self.assertEqual(doc['repair']['demonstrated'],1)
        self.assertEqual(doc['pullRequest']['fixLinks'],[{'line':2,'text':'Fixes #284'}])
        self.assertIn('line 2',(self.root/'report/review/index.html').read_text())
        self.assertIn(comment.md('Fixes #284'),comment.render(doc,ci.ctx()))
        self.assertEqual(record.read_record(self.root/'report/findings.json'),doc)

    def test_linked_fix_with_passing_base_needs_review_and_downgraded_bundle_is_refused(self):
        (self.base/'game/platformer/BUG').unlink()
        self.pr=intent.pull_request_metadata({'number':7,'head':{'sha':ci.HEAD},'base':{'sha':ci.BASE},'body':'Closes #284'})
        self.capture('fix');doc=self.judge('fix')
        self.assertEqual(doc['decision'],'needs-review')
        self.assertTrue(doc['reasons'][0].startswith('repair-not-demonstrated'))
        with self.assertRaisesRegex(ValueError,'EVIDENCE_MISMATCH'):self.judge('none')

    def test_bundle_reader_refuses_linked_none_before_any_observer(self):
        self.pr=dict(self.pr,fixLinks=[{'line':1,'text':'Fixes #284'}]);self.capture('fix')
        edited=self.root/'edited.zip'
        with zipfile.ZipFile(self.archive) as source,zipfile.ZipFile(edited,'w',zipfile.ZIP_STORED) as target:
            for name in source.namelist():
                data=source.read(name)
                if name=='manifest.json':
                    doc=json.loads(data);doc['intent']='none';data=json.dumps(doc).encode()
                target.writestr(name,data)
        self.archive=edited
        with self.assertRaisesRegex(ValueError,'closing-keyword links require fix capture'):self.judge('none')
        self.assertFalse(self.model.asked)


class TrustedComment(unittest.TestCase):
    setUp=pr_tests.TheTrustedJob.setUp
    gate=pr_tests.TheTrustedJob.gate
    run_with=pr_tests.TheTrustedJob.run_with
    accepted=pr_tests.TheTrustedJob.accepted

    def test_a_closing_link_blocks_a_record_that_dropped_intent(self):
        result,text=self.run_with(self.accepted(),['intent:none'],'Fixes #284')
        self.assertEqual(result['decision'],'needs-review')
        self.assertIn('line 1',text)
        self.assertNotIn('### Expectrail: accept',text)

    def test_legacy_fix_record_comment_gets_fresh_line_and_reject_stays_reject(self):
        result,text=self.run_with(pr_tests.fix_record(),body='Text\nCloses #284')
        self.assertIsNone(result['problem']);self.assertIn('line 2',text)
        self.assertIn('Closes',text)
        result,text=self.run_with(ci.head_example(),body='Resolves #284')
        self.assertEqual(result['decision'],'reject');self.assertIn('line 1',text)

    def test_stale_record_source_cannot_be_published_as_accept(self):
        doc=pr_tests.fix_record()
        doc['pullRequest']['fixLinks']=[{'line':1,'text':'Closes #284'}]
        result,text=self.run_with(doc,body='New explanation\nCloses #284')
        self.assertEqual(result['decision'],'needs-review')
        self.assertIn('recorded closing',result['problem']);self.assertIn('line 2',text)


class EventCLI(unittest.TestCase):
    def test_event_reader_bounds_bytes_before_decoding(self):
        with mock.patch.object(intent,'MAX_EVENT_BYTES',10), \
             mock.patch.object(Path,'open',mock.mock_open(read_data=b'x'*100)) as opened:
            with self.assertRaisesRegex(ValueError,'too large'):intent.of_event(Path('event.json'))
            opened.return_value.read.assert_called_once_with(11)

    def test_existing_action_event_also_supplies_report_provenance(self):
        pr={'number':7,'head':{'sha':ci.HEAD},'base':{'sha':ci.BASE},'body':'Summary\nFixes #284','labels':[]}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'event.json';path.write_text(json.dumps({'pull_request':pr}))
            with mock.patch.dict(os.environ,{'GITHUB_EVENT_PATH':str(path)}):
                metadata,selected=intent.ci_context({'number':7,'headSha':ci.HEAD,'baseSha':ci.BASE},'none',path)
            self.assertEqual(selected,'fix');self.assertEqual(metadata['fixLinks'][0]['line'],2)
            with mock.patch.dict(os.environ,{'GITHUB_EVENT_PATH':str(path)}), \
                 self.assertRaises(ValueError):
                intent.ci_context({'number':8,'headSha':ci.HEAD,'baseSha':ci.BASE},'none',path)

    def test_actual_legacy_gate_command_tightens_none_and_refuses_mismatched_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);event=root/'event.json'
            event.write_text(json.dumps({'pull_request':{'number':7,'head':{'sha':ci.HEAD},
                'base':{'sha':ci.BASE},'body':'Summary\nCloses #284'}}))
            args=['--repo',str(root),'--game','game/platformer','--routes','routes/*.json','--specs','specs',
                  '--out',str(root/'out'),'--pr','7','--head-sha',ci.HEAD,'--base-sha',ci.BASE,'--intent','none']
            doc=record.read_record(Path(__file__).resolve().parents[1]/'contracts/examples/findings-linked-fix.json')
            with mock.patch.dict(os.environ,{'GITHUB_EVENT_PATH':str(event)}), \
                 mock.patch.object(verify,'run_gate',return_value=doc) as gate, \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verify.main(args),verify.EXIT['needs-review'])
                self.assertEqual(gate.call_args.kwargs['intent'],'fix')
                self.assertEqual(gate.call_args.kwargs['pr']['fixLinks'],[{'line':2,'text':'Closes #284'}])
            args[args.index('--pr')+1]='8';args[args.index('--out')+1]=str(root/'other')
            with mock.patch.dict(os.environ,{'GITHUB_EVENT_PATH':str(event)}), \
                 mock.patch.object(verify,'run_gate') as gate,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verify.main(args),3);gate.assert_not_called()
            self.assertFalse((root/'other').exists())


class HeadSnapshot(unittest.TestCase):
    setUp=ci.HeadChecksTest.setUp
    api=ci.HeadChecksTest.api

    def test_a_body_edit_that_keeps_fix_intent_still_invalidates_the_source_lines(self):
        self.pr['body']='Fixes #284'
        self.state.update(pr=intent.pull_request_metadata(self.pr),intent='fix')
        self.assertTrue(ci_checks.current(self.api,ci.ctx(),self.run,self.state))
        self.pr['body']='New explanation\nFixes #284'
        self.assertEqual(intent.of_pull_request(self.pr).intent,'fix')
        self.assertFalse(ci_checks.current(self.api,ci.ctx(),self.run,self.state))


class BenchDriver(unittest.TestCase):
    def test_existing_bench_and_decision_receive_only_fixed_routes_specs_and_stricter_intent(self):
        from tools import linked_bug_bench as driver
        cases=driver.bench.load_cases();names=[c['case'] for c in cases]
        fake=fake_gate({n:['pass']*3 for n in names},{n:'pass' for n in names})
        def gate(**kw):
            self.assertEqual(kw.pop('rule'),record.ENGINE_ONLY);kw.pop('replay')
            pr=kw.pop('pr')
            self.assertEqual(bool(pr.get('fixLinks')),kw['intent']=='fix')
            return fake(**kw)
        # Unit tests must also run in a depth-one CI checkout without BEFORE's
        # historical object. Only the recorded real-engine run loads that source.
        before=mock.Mock(of_pull_request=lambda pr:intent.Declared('none'))
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()), \
             mock.patch.object(driver,'baseline',return_value=before):
            doc,source=driver.run('approval: approved\nFixes #284\nExpectrail-Intent: none',Path(tmp),run_gate=gate)
            self.assertEqual(source['gateCalls'],16)
            self.assertEqual(doc['totals']['wrongAcceptToNeedsReview'],4)
            for call in fake.calls:
                self.assertEqual(call['routes'],['harness/routes/smoke.json','harness/routes/combat.json'])
                self.assertEqual(call['specs'],'agents/specs')
            with self.assertRaisesRegex(ValueError,'before any replay'):
                driver.run('Part of #284',Path(tmp)/'no',run_gate=mock.Mock(side_effect=AssertionError('replay')))


class Contracts(unittest.TestCase):
    def test_findings_and_bundle_examples_and_stricter_reader(self):
        root=Path(__file__).resolve().parents[1]
        doc=record.read_record(root/'contracts/examples/findings-linked-fix.json')
        self.assertIn('line 2',record.repair_words(doc))
        contracts.validate(json.loads((root/'contracts/examples/ci-bundle-linked-fix.json').read_text()),ci_bundle.SCHEMA)
        wrong=copy.deepcopy(doc);wrong.pop('intent');wrong.pop('repair')
        wrong['decision']='accept';wrong['reasons']=['all checks pass']
        with self.assertRaises(record.RecordError):record.check_record(wrong)
        for change in ({'line':0,'text':'Fixes #284'},{'line':True,'text':'Fixes #284'},
                       {'line':1,'text':'Fixes #284','approve':True}):
            wrong=copy.deepcopy(doc);wrong['pullRequest']['fixLinks']=[change]
            with self.assertRaises(record.RecordError):record.check_record(wrong)
