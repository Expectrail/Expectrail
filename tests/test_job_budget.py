"""Verify jobs keep spend's records, using offline holds and stand-in engines."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

import jsonschema

from expectrail import cli as public_cli, spend
from expectrail.orchestrator import budget, cli, engines, request, runner, store
from tests.test_ci_gate import make_repo

ROOT = Path(__file__).resolve().parents[1]


class Engine:
    def __init__(self, action=lambda: None, *, evidence=True):
        self.action, self.evidence = action, evidence
        self.started = False

    def preflight(self, req):
        self.started = True
        return []

    def execute(self, req, paths, advance):
        if self.evidence:
            paths.staging.mkdir()
            (paths.staging / 'evidence.txt').write_text('stand-in evidence')
        self.action()
        advance('evaluating')
        return engines.Result('accept')


class JobBudgetTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.head = make_repo(self.root/'head', routes=('smoke',))
        self.jobs = store.JobStore(self.root/'jobs')
        env = {k:v for k,v in os.environ.items()
               if k not in (*spend.CAP_ENV.values(), spend.LEDGER_ENV, 'MODEL_API_KEY')}
        self.enterContext(mock.patch.dict(os.environ, env, clear=True))
        self.enterContext(mock.patch.object(spend, 'METER', spend.Meter()))
        self.enterContext(mock.patch.object(spend, '_month_status', {
            'limitUsd':200, 'spentUsd':0, 'runWorstCaseUsd':None, 'admitted':False}))
        self.vision = [0.0, 0]
        self.enterContext(mock.patch.object(spend, '_vision_reserved', side_effect=lambda: tuple(self.vision)))

    def job(self):
        req = request.build(adapter='godot', head=self.head, game='game/platformer',
                            routes=['routes/smoke.json'], specs='specs')
        return self.jobs.create(req)[0]['id']

    def work(self, engine, job=None):
        job = job or self.job()
        with contextlib.redirect_stderr(io.StringIO()):
            status = runner.work(self.jobs, job, engines={'godot':engine})
        self.assertEqual(status, self.jobs.status(job))
        self.assertEqual(status['budget'], spend.read_job_budget(self.jobs.paths(job).budget))
        jsonschema.Draft202012Validator(budget.schema()).validate(status['budget'])
        store.check_status(status)
        return status

    def test_invalid_cap_reports_safely_without_losing_any_cost(self):
        for role in spend.ROLES:
            os.environ[spend.CAP_ENV[role]] = '2'
        for role in ('glimmer','muse','triage'):
            spend.hold(role, live=False)
        self.vision[:] = [.25, 100]
        before = spend.build_job_budget('probe')
        secret = 'private-value-not-to-be-recorded'
        os.environ[spend.CAP_ENV['muse']] = secret
        spend.note_stop('muse', f'{spend.CAP_ENV["muse"]} must be an amount; {secret}')
        after = spend.build_job_budget('probe')
        self.assertEqual(after['totalReservedUsd'], before['totalReservedUsd'])
        self.assertEqual([(r['reservedUsd'],r['requests']) for r in after['phases']],
                         [(r['reservedUsd'],r['requests']) for r in before['phases']])
        self.assertIsNone(after['capsUsd']['muse'])
        self.assertEqual(after['stopped'], 'EXPECTRAIL_MUSE_USD_CAP is not an amount')
        self.assertNotIn(secret, json.dumps(after))
        jsonschema.Draft202012Validator(budget.schema()).validate(after)
        with self.assertRaises(spend.BudgetStop):
            spend.hold('muse', live=False)  # reporting did not weaken sending

    def test_every_invalid_amount_is_recorded_and_every_sender_still_refuses(self):
        for bad in ('wrong', '-1', 'NaN', 'Infinity', '-Infinity'):
            with self.subTest(bad=bad), mock.patch.dict(os.environ, {'EXPECTRAIL_TRIAGE_USD_CAP':bad}):
                doc = spend.build_job_budget('probe')
                self.assertEqual(doc['stopped'], 'EXPECTRAIL_TRIAGE_USD_CAP is not an amount')
                self.assertIsNone(doc['capsUsd']['triage'])
                with self.assertRaises(spend.BudgetStop):
                    spend.require_cap('triage')
        with mock.patch.dict(os.environ, {'EXPECTRAIL_MUSE_USD_CAP':'bad','EXPECTRAIL_TRIAGE_USD_CAP':'bad'}):
            doc = spend.build_job_budget('probe')
            for role in ('muse','triage'):
                self.assertIn(spend.CAP_ENV[role],doc['stopped'])

    def test_a_malformed_cap_job_is_needs_review_with_a_valid_budget(self):
        os.environ['EXPECTRAIL_TRIAGE_USD_CAP'] = 'do-not-print-this-value'
        engine = Engine()
        status = self.work(engine)
        self.assertTrue(engine.started)  # preserve the engine-only evidence path
        self.assertEqual((status['phase'],status['decision']),('completed','needs-review'))
        self.assertEqual(status['budget']['stopped'],'EXPECTRAIL_TRIAGE_USD_CAP is not an amount')
        self.assertIn('BUDGET_STOP', status['reasons'][0])
        self.assertNotIn('do-not-print-this-value', json.dumps(status))
        self.assertIn('BUDGET_STOP',[d['code'] for d in status['diagnostics']])

    def test_a_cap_becoming_invalid_preserves_this_jobs_prior_cost_and_never_echoes_its_value(self):
        os.environ['EXPECTRAIL_TRIAGE_USD_CAP'] = '.2'
        def action():
            spend.hold('triage',live=False)
            os.environ['EXPECTRAIL_TRIAGE_USD_CAP'] = 'private-bad-cap'
            spend.require_cap('triage')
        status = self.work(Engine(action))
        self.assertEqual(status['decision'],'needs-review')
        self.assertEqual(status['budget']['totalReservedUsd'],.05)
        self.assertEqual(status['budget']['phases'][0]['requests'],1)
        self.assertNotIn('private-bad-cap',json.dumps(status))

    def test_verify_cli_returns_the_stopped_budget_as_json(self):
        os.environ['EXPECTRAIL_TRIAGE_USD_CAP']='not-a-publishable-cap-value'
        engine=Engine()
        def launch(jobs,job):
            runner.work(jobs,job,engines={'godot':engine})
            return None
        out=io.StringIO()
        with mock.patch.object(runner,'spawn',side_effect=launch),contextlib.redirect_stdout(out):
            code=public_cli.main(['verify','--head',str(self.head),'--game','game/platformer',
                '--routes','routes/smoke.json','--specs','specs','--jobs-root',str(self.jobs.root),'--json'])
        self.assertEqual(code,2)
        doc=json.loads(out.getvalue())
        self.assertEqual(doc['decision'],'needs-review')
        self.assertEqual(doc['budget'],spend.read_job_budget(self.jobs.paths(doc['id']).budget))
        self.assertIn('EXPECTRAIL_TRIAGE_USD_CAP',doc['budget']['stopped'])
        self.assertNotIn('not-a-publishable-cap-value',out.getvalue())

    def test_budget_stop_is_needs_review_with_counted_requests_and_stop_reason(self):
        os.environ['EXPECTRAIL_TRIAGE_USD_CAP'] = '.1'
        def action():
            for _ in range(3): spend.hold('triage',live=False)
        status = self.work(Engine(action))
        self.assertEqual(status['decision'],'needs-review')
        self.assertEqual(status['budget']['totalReservedUsd'],.1)
        self.assertEqual(status['budget']['phases'][0]['requests'],2)
        self.assertIn('next request',status['budget']['stopped'])
        self.assertEqual(cli.exit_code(status),2)

    def test_a_swallowed_budget_stop_cannot_publish_an_accept(self):
        os.environ['EXPECTRAIL_TRIAGE_USD_CAP'] = '0'
        def action():
            try: spend.hold('triage',live=False)
            except spend.BudgetStop: pass
        status = self.work(Engine(action))
        self.assertEqual(status['decision'],'needs-review')
        self.assertTrue(status['budget']['stopped'])
        corrupted = dict(status,decision='accept')
        with self.assertRaises(store.StoreError): store.check_status(corrupted)

    def test_a_recorded_invalid_cap_stop_is_not_cleared_by_later_configuration(self):
        os.environ['EXPECTRAIL_TRIAGE_USD_CAP']='invalid'
        def action():
            os.environ['EXPECTRAIL_TRIAGE_USD_CAP']='1'
            spend.hold('triage',live=False)
        status=self.work(Engine(action))
        self.assertEqual(status['decision'],'needs-review')
        self.assertEqual(status['budget']['totalReservedUsd'],.05)
        self.assertEqual(status['budget']['stopped'],'EXPECTRAIL_TRIAGE_USD_CAP is not an amount')

    def test_a_stop_not_noted_by_the_sender_is_recorded(self):
        def action():
            raise spend.BudgetStop('the configured job budget is exhausted',role='triage')
        status = self.work(Engine(action))
        self.assertEqual(status['decision'],'needs-review')
        self.assertEqual(status['budget']['stopped'],'the configured job budget is exhausted')
        self.assertEqual(status['budget']['phases'][0]['requests'],0)

    def test_costs_are_per_job_not_inherited_process_totals_or_stops(self):
        os.environ['EXPECTRAIL_TRIAGE_USD_CAP'] = '.1'
        def action():
            for _ in range(3): spend.hold('triage',live=False)
        one = self.work(Engine(action))
        self.assertEqual(one['decision'],'needs-review')
        os.environ['EXPECTRAIL_TRIAGE_USD_CAP'] = '1'
        two = self.work(Engine(lambda: spend.hold('triage',live=False)))
        self.assertEqual(two['decision'],'accept')
        self.assertEqual(two['budget']['totalReservedUsd'],.05)
        self.assertIsNone(two['budget']['stopped'])
        self.assertNotEqual(one['budget']['jobId'],two['budget']['jobId'])
        self.assertEqual(self.jobs.status(one['id'])['budget'],one['budget'])

    def test_status_json_and_report_show_the_same_phase_costs_and_caps(self):
        for role in spend.ROLES: os.environ[spend.CAP_ENV[role]] = '2'
        def action():
            self.vision[:] = [.0075,3]
            for role in ('glimmer','muse','triage'): spend.hold(role,live=False)
        status = self.work(Engine(action))
        self.assertEqual(status['decision'],'accept')
        args=[status['id'],'--jobs-root',str(self.jobs.root)]
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            code=public_cli.main(['status',*args,'--json'])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(out.getvalue())['budget'],status['budget'])
        out=io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(io.StringIO()):
            code=public_cli.main(['report',*args])
        self.assertEqual(code,0)
        for words in ('observing: $0.057500','fixing: $1.000000','triaging: $0.050000',
                      'not a provider bill','vision cap: $2','job-budget.json'):
            self.assertIn(words,out.getvalue())

    def test_budget_file_cannot_stand_in_for_missing_verification_evidence(self):
        status=self.work(Engine(evidence=False))
        self.assertEqual((status['phase'],status['decision']),('failed',None))
        self.assertTrue(self.jobs.paths(status['id']).budget.is_file())
        self.assertIsNone(status['output'])

    def test_budget_updates_do_not_undo_cancellation(self):
        os.environ['EXPECTRAIL_TRIAGE_USD_CAP']='1'
        job=self.job()
        def action():
            spend.hold('triage',live=False)
            self.jobs.finish(job,'cancelled',reasons=['cancelled on request'])
        status=self.work(Engine(action),job)
        self.assertEqual((status['phase'],status['decision']),('cancelled',None))
        self.assertEqual(status['budget']['totalReservedUsd'],.05)

    def test_running_job_exposes_a_snapshot_before_completion(self):
        os.environ['EXPECTRAIL_TRIAGE_USD_CAP']='1'
        ready,release=threading.Event(),threading.Event()
        class Paused(Engine):
            def execute(self,req,paths,advance):
                spend.hold('triage',live=False)
                advance('observing')
                ready.set()
                if not release.wait(10): raise RuntimeError('test did not release worker')
                return super().execute(req,paths,advance)
        job=self.job()
        results=[]
        worker=threading.Thread(target=lambda: results.append(runner.work(self.jobs,job,engines={'godot':Paused()})))
        worker.start()
        try:
            self.assertTrue(ready.wait(10))
            status=self.jobs.status(job)
            self.assertEqual(status['phase'],'observing')
            self.assertEqual(status['budget']['totalReservedUsd'],.05)
            self.assertEqual(spend.read_job_budget(self.jobs.paths(job).budget),status['budget'])
        finally:
            release.set();worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0]['decision'],'accept')

    def test_the_example_validates_and_bad_totals_roles_and_job_binding_are_refused(self):
        doc=json.loads((ROOT/'contracts/examples/verify-job-budget.json').read_text())
        jsonschema.Draft202012Validator(store.schema()).validate(doc)
        from referencing import Registry,Resource
        raw=json.loads(store.SCHEMA_PATH.read_text())
        registry=Registry().with_resource('https://expectrail.tech/contracts/job-budget.v1.schema.json',
                                          Resource.from_contents(budget.schema()))
        jsonschema.Draft202012Validator(raw,registry=registry).validate(doc)
        store.check_status(doc)
        for mutate in (lambda b:b.update(jobId='another-job'),
                       lambda b:b.update(totalReservedUsd=99),
                       lambda b:b['phases'].append(copy.deepcopy(b['phases'][0])),
                       lambda b:b['phases'][0].update(phase='fixing'),
                       lambda b:b.update(totalReservedUsd=float('nan'))):
            bad=copy.deepcopy(doc);mutate(bad['budget'])
            with self.assertRaises(store.StoreError): store.check_status(bad)
        legacy=copy.deepcopy(doc);legacy.pop('budget');store.check_status(legacy)

    def test_the_builder_and_worker_need_no_optional_jsonschema_package(self):
        req=request.build(adapter='instant',head=self.head,game='game/platformer',routes=['routes/smoke.json'],specs='specs')
        job=self.jobs.create(req)[0]['id']
        code='''import importlib.util, json, sys
from pathlib import Path
from expectrail import spend
from expectrail.orchestrator import runner, store
from tests.orchestrator_worker import ENGINES
assert importlib.util.find_spec("jsonschema") is None
jobs=store.JobStore(Path(sys.argv[1]))
status=runner.work(jobs,sys.argv[2],engines=ENGINES)
assert status["decision"]=="accept",status
assert status["budget"]["totalReservedUsd"]==0,status
print(json.dumps(status["budget"]))
'''
        done=subprocess.run([sys.executable,'-S','-c',code,str(self.jobs.root),job],cwd=ROOT,
                            capture_output=True,text=True,timeout=20)
        self.assertEqual(done.returncode,0,done.stderr)
        self.assertEqual(json.loads(done.stdout)['jobId'],job)

    def test_spawn_names_the_job_for_the_spend_ledger(self):
        job=self.job()
        fake=mock.Mock(pid=os.getpid())
        with mock.patch.object(runner.subprocess,'Popen',return_value=fake) as popen:
            runner.spawn(self.jobs,job)
        env=popen.call_args.kwargs['env']
        self.assertEqual(env[store.JOB_ENV],job)
        self.assertEqual(env[spend.JOB_ENV],job)


if __name__ == '__main__':
    unittest.main()
