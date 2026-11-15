"""The public verify CLI uses the shared repair rule, with offline replay and vision.

The seeded patches are applied only to disposable copies of the bundled game.
Game supplies synthetic frames/answers, not measured engine or model evidence.
"""
import contextlib
import io
import html
import json
import os
from pathlib import Path
import subprocess
import re
import shlex
import sys
import tempfile
import unittest
from unittest import mock

import jsonschema
from expectrail import cli as public_cli
from expectrail import viewer
from expectrail.gate import record as rec
from expectrail.orchestrator import cli, engines, request as req, runner, sample, store
from tests.test_ci_gate import make_repo
from tests.test_two_observers import Game, REPO

WORDS = 'No check reproduced the reported bug, so this fix is not verified'
REPORT = 'The player no longer falls through the floor.'


class RequestIntent(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.head = make_repo(self.root / 'head', routes=('smoke',))
        self.kw = dict(adapter='godot', head=self.head, game='game/platformer', routes=['routes/smoke.json'], specs='specs')

    def test_all_intents_validate_and_none_preserves_the_old_request_and_digest(self):
        plain = req.build(**self.kw)
        self.assertEqual(req.build(**self.kw, intent='none'), plain)
        self.assertEqual(req.inputs(dict(plain, intent='none')), req.inputs(plain))
        for intent in rec.INTENTS:
            doc = dict(plain, intent=intent)
            req.check(doc)
            jsonschema.Draft202012Validator(req.schema()).validate(doc)
        self.assertNotEqual(req.inputs(dict(plain, intent='fix')), req.inputs(plain))

    def test_bug_is_captured_text_and_changes_the_idempotency_meaning(self):
        one = req.build(**self.kw, intent='fix', bug=REPORT, idempotency_key='intent-test')
        two = dict(one, bug='A different reported bug.')
        req.check(two)
        self.assertNotEqual(req.inputs(one)['requestDigest'], req.inputs(two)['requestDigest'])
        jobs = store.JobStore(self.root / 'jobs')
        status, created = jobs.create(one)
        self.assertTrue(created)
        self.assertEqual(jobs.request(status['id']), one)
        self.assertEqual((status['intent'], status['bug']), ('fix', REPORT))
        self.assertEqual(jobs.status(status['id'])['bug'], REPORT)
        with self.assertRaises(store.IdempotencyConflict):
            jobs.create(two)
        with self.assertRaises(store.IdempotencyConflict):
            jobs.create(req.build(**self.kw, idempotency_key='intent-test'))

    def test_invalid_intents_and_misplaced_or_invalid_reports_are_refused(self):
        plain = req.build(**self.kw)
        for intent in ('Fix', 'typo', '', None, 1):
            with self.subTest(intent=intent), self.assertRaises(req.RequestError):
                req.check(dict(plain, intent=intent))
        for extra in ({'bug': REPORT}, {'intent':'none','bug':REPORT}, {'intent':'change','bug':REPORT},
                      *({'intent':'fix','bug':b} for b in ('', ' \n\t', 'x'*8193, '\x00bad', '\x1bbad', None))):
            with self.subTest(extra=repr(extra)[:60]), self.assertRaises(req.RequestError):
                req.check(dict(plain, **extra))
        # Existing auto-fix callers already send fix without a report.
        req.check(dict(plain, intent='fix'))

    def test_request_and_job_examples_have_both_readers(self):
        for name, schema, check in [('verify-request-fix',req.schema(),req.check),
                                    ('verify-job-fix',store.schema(),store.check_status)]:
            doc = json.loads((REPO/'contracts/examples'/f'{name}.json').read_text())
            self.assertEqual((doc['intent'],doc['bug']),('fix',REPORT))
            jsonschema.Draft202012Validator(schema).validate(doc)
            check(doc)
            bad = dict(doc, intent='change')
            with self.assertRaises((req.RequestError,store.StoreError)):
                check(bad)

    def test_bad_cli_inputs_start_no_job(self):
        args = ['verify','--head',str(self.head),'--game','game/platformer','--routes','routes/smoke.json',
                '--specs','specs','--jobs-root',str(self.root/'jobs')]
        missing = self.root/'missing.txt'
        huge = self.root/'huge.txt'; huge.write_text('x'*32769)
        invalid = self.root/'invalid.txt'; invalid.write_bytes(b'\xff')
        link = self.root/'link.txt'; link.symlink_to(huge)
        cases = [['--intent','typo'], ['--bug',REPORT], ['--intent','change','--bug',REPORT],
                 ['--intent','fix','--bug',''], ['--intent','fix','--bug','  ']]
        cases += [['--intent','fix','--bug','@'+str(p)] for p in (missing,huge,invalid,link,self.root)]
        with mock.patch.object(runner,'spawn') as spawn:
            for extra in cases:
                with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(public_cli.main(args+extra),cli.EXIT_USAGE)
            spawn.assert_not_called()
        self.assertFalse(list((self.root/'jobs').glob('*/request.json')))

    def test_a_report_cannot_queue_a_request_too_large_for_the_worker(self):
        # Within the character limit, but JSON's escaped spelling exceeds 64 KiB.
        with self.assertRaisesRegex(req.RequestError,'saved request exceeds'):
            req.build(**self.kw,intent='fix',bug='\U0001f600'*8192)
        doc=req.build(**self.kw,intent='fix',bug='\U0001f600'*100)
        jobs=store.JobStore(self.root/'unicode-jobs')
        status,_=jobs.create(doc)
        self.assertEqual(jobs.request(status['id']),doc)

    def test_a_fifo_is_refused_without_waiting_for_a_writer(self):
        fifo=self.root/'report.pipe';os.mkfifo(fifo)
        result=subprocess.run([sys.executable,'-c',
            'from expectrail.orchestrator.request import bug_text; bug_text(__import__("sys").argv[1])',
            '@'+str(fifo)],cwd=REPO,capture_output=True,text=True,timeout=5)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('regular file',result.stderr)

    def test_viewer_commands_preserve_intent_and_literal_captured_report(self):
        for report in (REPORT, '@not-a-file', '--not-an-option',
                       '@' + 'Quotes \'"; $(not-a-command) `not-a-command`\n' * 50):
            with self.subTest(report=report[:40]):
                doc=req.build(**self.kw,intent='fix',bug=report)
                folder=self.root/'viewer'
                viewer.write(folder,None,request=doc)
                for name in ('index.html',viewer.EXPORT_NAME):
                    page=(folder/name).read_text()
                    command=html.unescape(re.search(r'<h2>Reproduce</h2>.*?<pre>(.*?)</pre>',page,re.S).group(1))
                    argv=shlex.split(command)
                    self.assertEqual(argv[:4],['expectrail','verify','--intent','fix'])
                    output=io.StringIO()
                    with mock.patch.object(runner,'spawn',return_value=None),contextlib.redirect_stdout(output):
                        code=public_cli.main(argv[1:]+['--jobs-root',str(self.root/'jobs'),'--detach','--json'])
                    self.assertEqual(code,0,output.getvalue())
                    job=json.loads(output.getvalue())['id']
                    saved=store.JobStore(self.root/'jobs').request(job)
                    self.assertEqual((saved['intent'],saved['bug']),('fix',report))

    def test_viewer_keeps_change_and_leaves_default_reproduction_unchanged(self):
        plain=req.build(**self.kw)
        self.assertEqual(viewer.reproduce(plain),viewer.reproduce(dict(plain,intent='none')))
        self.assertNotIn('--intent',shlex.split(viewer.reproduce(plain)))
        changed=shlex.split(viewer.reproduce(dict(plain,intent='change')))
        self.assertEqual(changed[:4],['expectrail','verify','--intent','change'])


class VerifyIntentCLI(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.base = sample.checkout(self.root/'base',bug=False)
        self.head = sample.checkout(self.root/'head',bug=False)
        self.game = Game()
        self.game.look_of = lambda g: 'BUG' if 'collision_mask = 14\n' in (g/'player/player.tscn').read_text() else 'clean'
        self.jobs = store.JobStore(self.root/'jobs')
        self.created = []

    def patch(self, checkout, patch):
        subprocess.run(['patch','-p1','--batch','--forward','--silent','-d',str(checkout/sample.GAME),
                        '-i',str(REPO/patch)],check=True,capture_output=True)

    def invoke(self, *extra, base=True, visual=True):
        gate = engines.GodotGate(replay=self.game.replay, visual=self.game.observer() if visual else None)
        def spawn(jobs, job):
            self.created.append(job)
            runner.work(jobs,job,engines={'godot':gate})
            return None
        args = ['verify','--head',str(self.head),'--game',sample.GAME,'--routes',sample.ROUTE,
                '--specs',sample.SPECS,'--jobs-root',str(self.jobs.root)]
        if base: args += ['--base',str(self.base)]
        output = io.StringIO()
        with mock.patch.object(runner,'spawn',side_effect=spawn), mock.patch.object(rec,'decide',wraps=rec.decide) as shared, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = public_cli.main(args+list(extra))
        self.assertTrue(self.created,output.getvalue())
        job = self.created[-1]
        status = self.jobs.status(job)
        doc = rec.read_record(self.jobs.paths(job).output/'findings.json')
        self.assertEqual(status['decision'],doc['decision'])
        self.assertTrue(any(c.kwargs.get('intent','none')==rec.intent_of(doc) for c in shared.call_args_list))
        return code,status,doc,output.getvalue()

    def test_real_seeded_fix_accepts_only_with_three_demonstrations(self):
        self.patch(self.base,sample.BUG)
        self.patch(self.head,sample.BUG)
        self.patch(self.head,'agents/fixtures/fix-collision-mask.patch')
        code,status,doc,text = self.invoke('--intent','fix','--bug',REPORT)
        self.assertEqual((code,status['decision']), (0,'accept'))
        self.assertEqual(doc['repair']['demonstrated'],1)
        row=doc['repair']['rows'][0]
        self.assertEqual((row['base'],row['head']),(['fail']*3,['pass']*3))
        self.assertEqual(doc['observers']['rule'],'both')
        self.assertEqual(len(self.game.replays),6)
        self.assertTrue(self.game.asked)
        self.assertEqual(self.jobs.request(status['id'])['bug'],REPORT)
        self.assertIn(REPORT,text)

    def test_known_bench_comment_only_fix_is_not_verified_and_default_is_unchanged(self):
        for checkout in (self.base,self.head): self.patch(checkout,'bugs/reported/air-jump.patch')
        self.patch(self.head,'bench/jit/known/air-jump/comment-only.patch')
        self.assertNotEqual((self.base/sample.GAME/'player/player.gd').read_bytes(),
                            (self.head/sample.GAME/'player/player.gd').read_bytes())
        # These ground-only stand-ins cannot reproduce the air-jump report.
        code,status,doc,text=self.invoke('--intent','fix','--bug','Infinite jump in the air')
        self.assertEqual((code,status['decision']),(2,'needs-review'))
        self.assertEqual(doc['repair']['demonstrated'],0)
        self.assertTrue(status['reasons'][0].startswith('repair-not-demonstrated:'))
        self.assertTrue(all(c['before']==c['after']=='pass' for c in doc['checks']))
        self.assertTrue(text.startswith(WORDS),text[:150])
        for flags in ((),('--intent','none'),('--intent','change')):
            code,plain,record,_=self.invoke(*flags)
            self.assertEqual((code,plain['decision']),(0,'accept'))
            self.assertNotIn('repair',record)
            if flags!=('--intent','change'):
                self.assertNotIn('intent',self.jobs.request(plain['id']))

    def test_still_failing_on_the_head_rejects(self):
        for checkout in (self.base,self.head): self.patch(checkout,sample.BUG)
        code,status,doc,text=self.invoke('--intent','fix','--bug',REPORT)
        self.assertEqual((code,status['decision']),(1,'reject'))
        self.assertTrue(all(c['after']=='fail' for c in doc['checks']))
        self.assertFalse(text.startswith(WORDS))

    def test_flaky_base_failure_is_not_a_demonstration(self):
        self.patch(self.base,sample.BUG)
        normal=self.game.look_of
        def flaky(game):
            seen=sum(look=='BUG' for _route,look,_frames in self.game.replays)
            return 'clean' if seen else normal(game)
        self.game.look_of=flaky
        code,status,doc,_=self.invoke('--intent','fix')
        self.assertEqual((code,status['decision']),(2,'needs-review'))
        self.assertEqual(doc['repair']['rows'][0]['base'],['fail','pass','pass'])
        self.assertEqual(doc['repair']['demonstrated'],0)
        self.assertIn('not 3 times of 3',status['reasons'][0])

    def test_no_base_or_no_vision_cannot_demonstrate_a_fix(self):
        code,status,doc,_=self.invoke('--intent','fix',base=False)
        self.assertEqual((code,status['decision']),(2,'needs-review'))
        self.assertIn('before the change was not judged',status['reasons'][0])
        self.patch(self.base,sample.BUG)
        code,status,doc,_=self.invoke('--intent','fix',visual=False)
        self.assertEqual((code,status['decision']),(2,'needs-review'))
        self.assertEqual(doc['repair']['demonstrated'],0)

    def test_bug_file_is_snapshotted_and_report_leads_with_missing_demonstration(self):
        bug=self.root/'bug.txt';bug.write_text(REPORT,encoding='utf-8')
        code,status,doc,_=self.invoke('--intent','fix','--bug','@'+str(bug))
        self.assertEqual((code,status['decision']),(2,'needs-review'))
        bug.write_text('changed after the request')
        self.assertEqual(self.jobs.request(status['id'])['bug'],REPORT)
        self.assertEqual(status['bug'],REPORT)
        out=io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(io.StringIO()):
            code=public_cli.main(['report',status['id'],'--jobs-root',str(self.jobs.root)])
        self.assertEqual(code,2)
        self.assertTrue(out.getvalue().startswith(WORDS),out.getvalue()[:150])
        self.assertIn(REPORT,out.getvalue())
        page=(self.jobs.paths(status['id']).root/'viewer/index.html').read_text()
        self.assertIn('a fix, and no check demonstrated the repair',page)
        self.assertNotIn('changed after the request',page)

    def test_literal_at_report_and_detached_request_keep_the_intent(self):
        args=['verify','--head',str(self.head),'--base',str(self.base),'--game',sample.GAME,
              '--routes',sample.ROUTE,'--specs',sample.SPECS,'--jobs-root',str(self.jobs.root),
              '--intent','fix','--bug','@@a literal report','--detach','--json']
        out=io.StringIO()
        with mock.patch.object(runner,'spawn',return_value=None),contextlib.redirect_stdout(out):
            code=public_cli.main(args)
        self.assertEqual(code,0)
        job=json.loads(out.getvalue())['id']
        self.assertEqual(self.jobs.request(job)['bug'],'@a literal report')
        self.assertEqual(self.jobs.status(job)['intent'],'fix')
        with contextlib.redirect_stdout(io.StringIO()):
            status=runner.work(self.jobs,job,engines={'godot':engines.GodotGate(replay=self.game.replay,visual=self.game.observer())})
        self.assertEqual(status['decision'],'needs-review')


if __name__ == '__main__':
    unittest.main()
