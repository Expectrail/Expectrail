"""#531 repair integration. Synthetic replays and stand-in vision; no live transports."""
import contextlib
import copy
import io
import json
from pathlib import Path
import unittest
from unittest import mock

from agents import escalation, fixer, gateway
from expectrail import cli, contracts, repair
from expectrail.gate import record
from expectrail.orchestrator import engines, ingest_repair, playtest, reproduction, runner
from tests import test_playtest_ingest as intake


class IngestRepair(unittest.TestCase):
    def setUp(self):
        intake.PlaytestIngest.setUp(self)
        self.game.look_of = lambda game: 'BUG' if (game/'BUG').is_file() and (game/'BUG').read_text() == '1\n' else 'clean'
        self.fix = self.root/'fix.patch'
        self.fix.write_text('--- a/BUG\n+++ b/BUG\n@@ -1 +1 @@\n-1\n+fixed\n')
        self.gate = engines.GodotGate(replay=self.game.replay, visual=self.game.observer())
        self.children = []
        self.after_child = None

    def invoke(self, *options, report=None):
        path = self.root/'report.json'; playtest.write(path, report or self.report)
        self.created = []
        def spawn(jobs, job):
            self.created.append(job)
            result = runner.work(jobs, job, {'godot': self.gate})
            if len(self.created) > 1:
                self.children.append(job)
                if self.after_child:
                    self.after_child(jobs, job)
            return None
        output = io.StringIO()
        with mock.patch.object(runner, 'spawn', side_effect=spawn), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = cli.main(['ingest', str(path), '--project', str(self.project), '--jobs-root', str(self.jobs.root), '--json', *options])
        return code, output.getvalue()

    def broken(self):
        (self.project/'BUG').write_text('1\n')

    def test_default_reproduces_but_never_enters_repair(self):
        self.broken()
        with mock.patch.object(repair, 'repair') as loop, mock.patch.object(fixer, 'run_fixer') as transport:
            code, text = self.invoke()
        self.assertEqual(code, 1, text)
        self.assertEqual(json.loads(text)['reproduction']['kind'], 'approved')
        loop.assert_not_called(); transport.assert_not_called()

    def test_opt_in_approved_three_of_three_uses_existing_loop_and_gate(self):
        self.broken()
        with mock.patch.object(repair, 'repair', wraps=repair.repair) as shared, mock.patch.object(fixer, 'run_fixer', wraps=fixer.run_fixer) as transport, mock.patch.object(record, 'decide', wraps=record.decide) as decide:
            code, text = self.invoke('--repair', '--repair-fixture', str(self.fix))
        self.assertEqual(code, 0, text)
        doc = json.loads(text); contracts.validate_v1(doc, 'repair-run')
        self.assertEqual(list(doc)[:3], ['format','reproduction','repairAttempted'])
        self.assertEqual(doc['reproduction']['kind'], 'approved'); self.assertTrue(doc['repairAttempted'])
        self.assertEqual(doc['result']['decision'], 'accept'); self.assertGreater(decide.call_count, 0)
        shared.assert_called_once(); transport.assert_called_once()
        self.assertTrue(transport.call_args.kwargs['require_sandbox'])
        parent = self.jobs.status(self.created[0]); self.assertEqual(parent['decision'], 'reject')
        proof = record.read_json(self.jobs.paths(parent['id']).output/'playtest-precheck.log')
        self.assertEqual([r['run'] for r in proof], [1,2,3])
        self.assertTrue(all(r['checks'][0]['result'] == 'fail' for r in proof))
        child = record.read_record(self.jobs.paths(doc['result']['job']).output/'findings.json')
        self.assertGreater(child['repair']['demonstrated'], 0)
        saved = list(self.jobs.paths(parent['id']).root.glob('repair-*/repair-run.json'))
        self.assertEqual(contracts.load_strict(saved[0], 'repair-run'), doc)

    def test_no_reproduction_and_desync_construct_no_transport(self):
        for desync in (False, True):
            report = copy.deepcopy(self.report)
            if desync: report['fault']['anchor']['x'] += 10000
            with self.subTest(desync=desync), mock.patch.object(repair,'repair') as loop, mock.patch.object(fixer,'run_fixer') as transport, mock.patch.object(gateway, 'muse_gateway') as factory, mock.patch('urllib.request.urlopen') as network:
                code, text = self.invoke('--repair', report=report)
                self.assertEqual(code,2,text)
                doc=json.loads(text)
                self.assertFalse(doc['repairAttempted']); self.assertEqual(doc['reproduction']['kind'],'none')
                self.assertIn('anchor-desync' if desync else 'not-reproduced',doc['stop']['detail'])
                loop.assert_not_called();transport.assert_not_called();factory.assert_not_called();network.assert_not_called()

    def test_generated_advisory_requires_person_and_constructs_no_transport(self):
        # The proposal subprocess is substituted at its existing boundary. The base replay/judge
        # and final CLI handoff are real. No synthetic generated check is made approved.
        def propose(doc,paths):
            base = json.loads(paths.status.read_text())['inputs']['baseTree']
            return reproduction.build('generated-advisory',['jit-'+'x'*80+'/body-facing'],'generated-advisory-reproduced',base_tree=base,jit_sha='a'*64)
        with mock.patch.object(reproduction,'propose',side_effect=propose), mock.patch.object(repair,'repair') as loop, mock.patch.object(fixer,'run_fixer') as transport, mock.patch.object(gateway,'muse_gateway') as factory:
            code,text=self.invoke('--repair','--propose')
        self.assertEqual(code,2,text);doc=json.loads(text)
        self.assertEqual(doc['reproduction']['kind'],'generated-advisory');self.assertFalse(doc['repairAttempted'])
        self.assertIn('a person must approve a check first',doc['stop']['detail'])
        loop.assert_not_called();transport.assert_not_called();factory.assert_not_called()

    def test_saved_three_of_three_proof_is_required_before_loop(self):
        self.broken();self.invoke()
        job=self.created[0];path=self.jobs.paths(job).output/'playtest-precheck.log'
        rows=json.loads(path.read_text());rows.pop();path.write_text(json.dumps(rows))
        with mock.patch.object(repair,'repair') as loop:
            _,doc=ingest_repair.run(self.jobs,job,fixture=self.fix)
        self.assertFalse(doc['repairAttempted']);loop.assert_not_called()
        self.assertIn('three-of-three',doc['stop']['detail'])

    def test_hostile_report_strings_do_not_choose_repair_checks_or_prompt(self):
        self.broken()
        for keys in [('bug',),('producer','name'),('producer','version'),('route','description')]:
            report=copy.deepcopy(self.report);node=report
            for key in keys[:-1]:node=node[key]
            node[keys[-1]]=intake.HOSTILE
            with self.subTest(field=keys), mock.patch.object(fixer,'run_fixer',wraps=fixer.run_fixer) as transport:
                code,text=self.invoke('--repair','--repair-fixture',str(self.fix),report=report)
                self.assertEqual(code,0,text)
                request=transport.call_args.args[0]
                self.assertNotIn(intake.HOSTILE,json.dumps(request))
                self.assertEqual({f['spec']['id'] for f in request['failing']},{'player-stays-above-ground'})

    def test_advisory_flag_stops_after_candidate_gate_accept_or_reject(self):
        for remains_buggy in (False,True):
            self.broken()
            patch=self.root/('bad.patch' if remains_buggy else 'good.patch')
            patch.write_text(self.fix.read_text().replace('+fixed','+1' if remains_buggy else '+fixed'))
            self.after_child=lambda jobs,job: write_discovery(jobs.paths(job).output, jobs.status(job)['inputs']['headTree'])
            with self.subTest(gate='reject' if remains_buggy else 'accept'), mock.patch.object(fixer,'run_fixer',wraps=fixer.run_fixer) as transport:
                code,text=self.invoke('--repair','--repair-attempts','3','--repair-fixture',str(patch))
                self.assertEqual(code,2,text);doc=json.loads(text)
                self.assertEqual(len(doc['attempts']),1);transport.assert_called_once()
                row=doc['attempts'][0]
                self.assertEqual(row['gateDecision'],'reject' if remains_buggy else 'accept')
                self.assertEqual(row['decision'],'needs-review');self.assertEqual(row['advisoryDiscovery'],['candidate-body-facing'])
                self.assertEqual(doc['stop']['reason'],'needs-review');self.assertIn('candidate-body-facing',doc['stop']['detail'])
                self.assertIsNone(doc['result']['patch'])

    def test_heldout_only_veto_retry_contains_only_public_failures(self):
        self.broken()
        from expectrail.gate import verify
        real=verify.run_gate
        def gate(**kwargs):
            doc=real(**kwargs)
            if kwargs['repo'] != Path(self.jobs.request(self.created[0])['head']['checkout']):
                # Synthetic counts only. Never read an actual held-out route or frame.
                doc['heldOut'].update(status='judged',routes=1,checks=1,passed=0,failed=1,needsReview=0)
                doc['decision'],doc['reasons']=record.decide(doc['counts'],doc['heldOut'],intent='fix',repair=doc['repair'],observers=doc['observers'])
                doc['isolation']['replays']+=1
                doc['reasons'].append('PRIVATE-REASON-CANARY')
                private = kwargs['out']/'private-artifacts';private.mkdir()
                (private/'PRIVATE-ROUTE.json').write_text('PRIVATE-ROUTE-CANARY')
                (private/'PRIVATE-FRAME.png').write_bytes(b'PRIVATE-FRAME-CANARY')
                (kwargs['out']/'findings.json').write_text(json.dumps(doc))
            return doc
        actual=fixer.run_fixer
        def inspect(req,out,**kwargs):
            for path in kwargs['game'].rglob('*'):
                if path.is_file():
                    self.assertNotIn(b'PRIVATE-',path.read_bytes())
            self.assertNotIn('PRIVATE-',json.dumps([req,kwargs.get('prior_reject')]))
            return actual(req,out,**kwargs)
        with mock.patch.object(verify,'run_gate',side_effect=gate),mock.patch.object(fixer,'run_fixer',side_effect=inspect) as transport:
            code,text=self.invoke('--repair','--repair-attempts','2','--repair-fixture',str(self.fix))
        self.assertEqual(code,2,text);doc=json.loads(text)
        self.assertEqual([a['gateDecision'] for a in doc['attempts']],['reject','reject'])
        self.assertEqual(transport.call_count,2)
        feedback=transport.call_args_list[1].kwargs['prior_reject']
        self.assertEqual(feedback,{'attempt':1,'decision':'reject','failing':[]})
        for call in transport.call_args_list:
            visible=json.dumps([call.args[0],call.kwargs.get('prior_reject')])
            self.assertNotIn('PRIVATE-',visible);self.assertNotIn('held-out',visible)
        # The older demo loop's retry projection has the same boundary, including frames/reasons.
        private={'decision':'reject','reasons':['PRIVATE-REASON-CANARY'], 'checks':[{'kind':'held-out','spec':'PRIVATE-SPEC','route':'PRIVATE-ROUTE','result':'fail','frame':'PRIVATE-FRAME','reason':'PRIVATE-REASON'}]}
        self.assertNotIn('PRIVATE-',json.dumps(escalation.public_feedback(private,1)))

    def test_existing_generated_checks_candidate_flag_is_not_ignored(self):
        self.broken()
        def flag(jobs,job):
            path=jobs.paths(job).output/'findings.json'
            doc=record.read_record(path)
            doc['generatedChecks']={'status':'ran','reason':None,'proposed':1,'valid':1,
                'strong':1,'weak':0,'catches':[{'specId':'jit-body-facing',
                'statement':'A synthetic advisory flag','strength':'strong'}],'runSha256':'f'*64}
            path.write_text(json.dumps(doc))
        self.after_child=flag
        with mock.patch.object(fixer,'run_fixer',wraps=fixer.run_fixer) as transport:
            code,text=self.invoke('--repair','--repair-fixture',str(self.fix))
        self.assertEqual(code,2,text);doc=json.loads(text)
        self.assertEqual(doc['stop']['reason'],'needs-review');transport.assert_called_once()
        self.assertEqual(doc['attempts'][0]['gateDecision'],'accept')
        self.assertIn('advisoryDiscovery',doc['attempts'][0],text)
        self.assertEqual(doc['attempts'][0]['advisoryDiscovery'],['jit-body-facing'])
        self.assertIn('jit-body-facing',doc['stop']['detail'])

    def test_contract_rejects_advisory_repair_and_flagged_accept(self):
        path=intake.REPO/'contracts/examples/repair-run-ingest.json'
        doc=contracts.load_strict(path,'repair-run')
        doc['reproduction']['kind']='generated-advisory'
        with self.assertRaises(contracts.ContractError):contracts.validate_v1(doc,'repair-run')
        doc=contracts.load_strict(path,'repair-run')
        doc['attempts'][0]['advisoryDiscovery']=['candidate-body-facing']
        with self.assertRaises(contracts.ContractError):contracts.validate_v1(doc,'repair-run')
        blocked=contracts.load_strict(intake.REPO/'contracts/examples/repair-run-ingest-blocked.json','repair-run')
        blocked['extra']='untrusted'
        with self.assertRaises(contracts.ContractError):contracts.validate_v1(blocked,'repair-run')

    def test_malformed_candidate_discovery_stops_for_review_without_retry(self):
        self.broken()
        self.after_child=lambda jobs,job: (jobs.paths(job).output/'discovery-run.json').write_text('{"format":"untrusted"}')
        with mock.patch.object(fixer,'run_fixer',wraps=fixer.run_fixer) as transport:
            code,text=self.invoke('--repair','--repair-fixture',str(self.fix))
        self.assertEqual(code,2,text);doc=json.loads(text)
        self.assertEqual(doc['stop']['reason'],'needs-review');transport.assert_called_once()
        self.assertEqual(doc['attempts'][0]['decision'],'needs-review')
        self.assertEqual(doc['attempts'][0]['gateDecision'],'accept')

    def test_repair_detach_and_options_without_opt_in_refused_before_job(self):
        with mock.patch.object(runner,'spawn') as spawn:
            for options in [('--repair','--detach'),('--repair-fixture',str(self.fix)),('--repair','--repair-attempts','11')]:
                code,text=self.invoke(*options);self.assertEqual(code,5,text)
            spawn.assert_not_called()


def write_discovery(folder,tree):
    """A strict stand-in for the existing discovery writer's candidate output."""
    doc={'format':'expectrail.discovery-run/v1','runId':'candidate','mode':'discover','evidenceLabel':'SAMPLE',
         'contextManifest':{'condition':'development-reproduction','supplied':[],'withheld':[]},
         'profile':{'id':'test','sha256':'1'*64},
         'snapshots':[{'name':'candidate','role':'base','patchSha256':None,'treeSha256':tree}],
         'stages':[],'probes':[],'verdicts':[],
         'findings':[{'id':'candidate-body-facing','snapshot':'candidate','specId':'body-facing','origin':'AUTO_TRACE',
                      'expectationRef':{},'probeIds':['reverse'],'lifecycle':'reproduced',
                      'reproduction':{'runs':3,'failures':3},'observation':'test flag','evidence':[],'alternatives':[]}],
         'candidates':[],'coverage':{},'usage':{'episodes':3,'wallSeconds':0},'completion':'complete',
         'stopReason':None,'diagnostics':[]}
    contracts.validate_v1(doc,'discovery-run')
    (folder/'discovery-run.json').write_text(json.dumps(doc))
