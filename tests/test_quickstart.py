"""The front door's commands/links and evidence checks, with no engine or model calls here.

CI additionally runs tools.quickstart: exactly the HTML command blocks, real pip install, doctor,
sample and project/report commands. That command fails, rather than skipping, without its tools.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from tools import front_door as front, quickstart as quick
from expectrail import doctor
from expectrail.orchestrator import cli, engines, request, runner, sample, store
from tests.test_ci_gate import FakeReplay, make_repo


class FrontDoorTest(unittest.TestCase):
    def test_links_fragments_and_all_four_pages_claims_are_in_the_ledger(self):
        self.assertEqual(front.problems(), [])

    def test_the_published_six_blocks_are_the_commands_read_by_ci(self):
        steps=quick.commands()
        self.assertEqual([(s['name'],s['exit']) for s in steps],quick.EXPECTED)
        self.assertIn('python3 -m pip install .',steps[0]['command'])
        self.assertIn('unset MODEL_API_KEY EXPECTRAIL_SAM_USD_CAP',steps[1]['command'])
        self.assertIn('--head "$PROJECT"',steps[4]['command'])
        self.assertNotIn('&amp;',steps[0]['command'])
        self.assertIn('&&',steps[0]['command'])

    def test_a_command_cannot_silently_disappear_or_change_its_expected_exit(self):
        text=(front.ROOT/'docs/quickstart.html').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'page.html'
            for changed in [text.replace('data-quickstart-step="sample"','data-quickstart-step="missing"'),
                            text.replace('data-exit="3"','data-exit="0"',1)]:
                p.write_text(changed)
                with self.assertRaises(ValueError):quick.commands(p)

    def test_the_shell_runs_the_exact_blocks_and_keeps_variables_between_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            steps=front.Page('<pre data-quickstart-step="one" data-exit="3"><code>WORD="same shell"\n(exit 3)</code></pre>'
                             '<pre data-quickstart-step="two" data-exit="0"><code>printf "%s" "$WORD" &gt; result.txt</code></pre>').steps
            quick.run_steps(steps,root,dict(os.environ),root/'log')
            self.assertEqual((root/'result.txt').read_text(),'same shell')
            steps[0]['exit']=0
            with self.assertRaisesRegex(ValueError,'unexpected exit'):
                quick.run_steps(steps,root,dict(os.environ),root/'bad-log')

    def test_links_are_resolved_locally_and_cannot_read_outside_the_checkout(self):
        root=front.ROOT;page=root/'docs/concepts.html'
        self.assertEqual(front.target(root,page,'https://github.com/Expectrail/Expectrail/blob/main/docs/capabilities.md#signing'),
                         (root/'docs/capabilities.md','signing'))
        self.assertIn('signing',front.anchors(root/'docs/capabilities.md'))
        self.assertNotIn('invented-row',front.anchors(root/'docs/capabilities.md'))
        with self.assertRaisesRegex(ValueError,'leaves checkout'):
            front.target(root,page,'../../outside')
        with self.assertRaisesRegex(ValueError,'restricted'):
            front.target(root,page,'fresh-blocked/not-opened.json')


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.work=Path(tmp.name)
        patch=mock.patch.dict(os.environ,{'MODEL_API_KEY':'','EXPECTRAIL_SAM_USD_CAP':''})
        patch.start();self.addCleanup(patch.stop)
        network=mock.patch('urllib.request.urlopen',side_effect=AssertionError('no live model'))
        self.sent=network.start();self.addCleanup(network.stop)
        doc=json.loads((front.ROOT/'contracts/examples/doctor.json').read_text())
        doc['checks']=[dict(c,status='ok',fix=None) for c in doc['checks'] if not c['id'].startswith('vision-')]
        doc['checks']+=doctor.document(doctor.vision_checks({}))['checks'];doc['ok']=False
        (self.work/'doctor.json').write_text(json.dumps(doc))
        jobs=store.JobStore(self.work/'runs/quickstart-sample');cases=[]
        for n,(name,_,_,expected) in enumerate(sample.CASES):
            head=make_repo(self.work/f'head-{n}',bug=n==1,routes=('smoke',))
            req=request.build(adapter='godot',head=head,game='game/platformer',routes=['routes/*.json'],specs='specs')
            status,_=jobs.create(req)
            with contextlib.redirect_stdout(io.StringIO()):
                status=runner.work(jobs,status['id'],engines={'godot':engines.GodotGate(replay=FakeReplay())})
            cases.append(dict(case=name,expected=expected,status=status,asExpected=status['decision']==expected))
        (self.work/'sample.json').write_text(json.dumps(cases))
        project=self.work/'tests/projects/crate-run'
        shutil.copytree(front.ROOT/'tests/projects/crate-run',project)
        jobs=store.JobStore(self.work/'runs/quickstart-project')
        req=request.build(adapter='godot',head=project,game='project',routes=['routes/*.json'],specs='specs')
        status,_=jobs.create(req)
        with contextlib.redirect_stdout(io.StringIO()):
            status=runner.work(jobs,status['id'],engines={'godot':engines.GodotGate(replay=FakeReplay())})
            self.assertEqual(cli.main(['report',status['id'],'--jobs-root',str(jobs.root)]),2)
        (self.work/'verification.json').write_text(json.dumps(status))

    def test_expected_results_have_real_records_and_preserve_the_draft_boundary(self):
        self.assertEqual(quick.validate_results(self.work),dict(sample=['needs-review','reject','needs-review'],
                         project='needs-review',drafts=1,projectReplays=0))
        self.sent.assert_not_called()

    def test_a_missing_tool_is_not_mistaken_for_the_expected_missing_vision_settings(self):
        p=self.work/'doctor.json';doc=json.loads(p.read_text());check=next(c for c in doc['checks'] if c['id']=='display')
        check.update(status='missing',required=True,fix='install a virtual display');p.write_text(json.dumps(doc))
        with self.assertRaises(AssertionError):quick.validate_results(self.work)

    def test_an_accept_without_vision_cannot_pass_the_quickstart_check(self):
        p=self.work/'sample.json';doc=json.loads(p.read_text());doc[0]['status']['decision']='accept';p.write_text(json.dumps(doc))
        with self.assertRaises(AssertionError):quick.validate_results(self.work)

    def test_a_missing_report_is_not_a_successful_sixth_step(self):
        doc=json.loads((self.work/'verification.json').read_text())
        page=store.JobStore(self.work/'runs/quickstart-project').paths(doc['id']).root/'viewer/index.html'
        page.unlink()
        with self.assertRaisesRegex(AssertionError,'report'):quick.validate_results(self.work)


if __name__=='__main__':unittest.main()
