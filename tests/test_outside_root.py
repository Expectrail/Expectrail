"""Root checkouts, draft-only trial evidence and bounded pointer summaries; no live provider."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from tools import outside_trial as trial
from expectrail import route

ROOT=trial.REPO

class RootTrialTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.project=copy.deepcopy(trial.load_list()[0]);self.project.update(path='.')
        self.source=self.root/'source';self.source.mkdir();(self.source/'project.godot').write_text('config_version=5\n')
        (self.source/'main.gd').write_text('extends Node\n')
    def test_root_is_accepted_but_traversal_absolute_and_newline_paths_are_not(self):
        file=self.root/'list.json'
        for value,allowed in [('.',True),('..',False),('../game',False),('/tmp',False),('a/../../b',False),('.\n',False),('a\n',False)]:
            p=dict(self.project,path=value);file.write_text(json.dumps({'format':trial.FORMAT,'projects':[p]}))
            if allowed:self.assertEqual(trial.load_list(file)[0]['path'],'.')
            else:
                with self.subTest(value=value),self.assertRaises(trial.TrialError):trial.load_list(file)
    def test_root_copy_omits_git_metadata_and_does_not_copy_links_out(self):
        (self.source/'.git').mkdir();(self.source/'.git/config').write_text('must not travel')
        result=trial.lay_out(self.project,self.source,self.root/'work')
        self.assertTrue((result/'project/main.gd').is_file());self.assertFalse((result/'project/.git').exists())
        outside=self.root/'private';outside.mkdir();(outside/'data').write_text('do not copy')
        for name,target in [('linked-file',outside/'data'),('linked-dir',outside),('broken-link',outside/'absent')]:
            link=self.source/name;link.symlink_to(target)
            with self.subTest(name=name),self.assertRaisesRegex(trial.TrialError,'link|outside'):
                trial.lay_out(self.project,self.source,self.root/'work')
            link.unlink()
    def test_nested_folder_link_out_is_refused_before_copy(self):
        (self.source/'game').symlink_to(self.root)
        with self.assertRaisesRegex(trial.TrialError,'link|outside'):
            trial.lay_out(dict(self.project,path='game'),self.source,self.root/'work')
    def test_root_sparse_checkout_fetches_at_full_pin_and_keeps_nested_assets(self):
        # Real local git transport exercises sparse patterns; never hits a network.
        repo=self.root/'upstream';repo.mkdir();subprocess.run(['git','init','-q',str(repo)],check=True)
        (repo/'project.godot').write_text('config_version=5\n');(repo/'art').mkdir();(repo/'art/x.txt').write_text('asset')
        subprocess.run(['git','add','.'],cwd=repo,check=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture'],cwd=repo,check=True)
        pin=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
        p=dict(self.project,repository=str(repo),commit=pin)
        clone=trial.fetch(p,self.root/'clones');self.assertEqual((clone/'art/x.txt').read_text(),'asset')
        self.assertEqual(subprocess.check_output(['git','rev-parse','HEAD'],cwd=clone,text=True).strip(),pin)
    def test_declared_verdict_and_each_draft_finding_are_required(self):
        row={'expect':'needs-review','verdict':'needs-review','expectedEngine':{'paddle':'fail'},'draftFindings':[{'spec':'paddle','result':'fail'}]}
        self.assertEqual(trial.expectation_errors(row),[])
        for changes in ({'verdict':'accept'},{'decision':'accept'},{'decision':None},{'draftFindings':[]},{'draftFindings':[{'spec':'paddle','result':'pass'}]}):
            with self.subTest(changes=changes):self.assertTrue(trial.expectation_errors(dict(row,**changes)))
    def test_new_modules_import_without_image_packages(self):
        script="""import builtins
old=builtins.__import__
def guarded(name,*args,**kwargs):
 if name.split('.')[0] in ('numpy','PIL'):raise AssertionError(name)
 return old(name,*args,**kwargs)
builtins.__import__=guarded
import tools.outside_trial, expectrail.route
"""
        proc=subprocess.run([sys.executable,'-c',script],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)

class PointerSummaryTest(unittest.TestCase):
    def test_generated_pointer_route_is_summarized_without_changing_events(self):
        p=ROOT/'tests/outside/breakout-pointer/routes/pointer-auto.json';doc=json.loads(p.read_text());before=copy.deepcopy(doc)
        lines=route.pointer_summary(doc['events'])
        self.assertEqual(len(lines),6,lines);self.assertIn('click',lines[0]);self.assertIn('12',lines[0]);self.assertIn('14',lines[0])
        self.assertEqual(sum('sweep' in s for s in lines),5);self.assertEqual(doc,before)
        text='\n'.join(route.describe(doc,60,{'rows':[]}));self.assertLess(len(text.splitlines()),10)
        self.assertIn('407',text)
    def test_hold_motion_unmatched_release_and_direction_changes_are_not_hidden(self):
        events=[{'tick':0,'pointer':{'position':[1,1],'button':'left','pressed':True}},
                {'tick':1,'pointer':{'position':[2,1]}},{'tick':2,'pointer':{'position':[3,1]}},
                {'tick':3,'pointer':{'position':[2,1]}},{'tick':4,'pointer':{'position':[2,1],'button':'left','pressed':False}},
                {'tick':5,'pointer':{'position':[2,1],'button':'right','pressed':False}}]
        lines=route.pointer_summary(events)
        self.assertIn('down',lines[0]);self.assertTrue(any('sweep' in s for s in lines));self.assertIn('right up',lines[-1])
        self.assertFalse(any('click' in s for s in lines))


class DraftTrialTest(unittest.TestCase):
    def setUp(self):
        self.project=next(p for p in trial.load_list() if p['name']=='breakout')
        self.spec=json.loads((ROOT/self.project['draftSpecs'][0]).read_text())
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def trace(self, frozen=None, broken=False):
        rows=[]
        for n in range(407):
            x=170.4-(n-20)*2.4 if 20<=n<=70 else 168
            if frozen is not None:x=frozen
            if broken:x=8
            # Tick-zero origin is outside the useful in-play window.
            point=[0,0] if n==0 else [x,616]
            box=[point[0]-23.5,point[1]-9,point[0]+23.5,point[1]+9]
            rows.append({'tick':n,'frame':n,'player':point,'playerVisible':True,
                         'roleObjects':[{'id':'Paddle','role':'player','worldBox':box,'box':box,'visible':True,'boundsSource':'drawing'},
                         {'id':'Ball','role':'ball','worldBox':[200,340,208,348],'box':[200,340,208,348],'visible':True,'boundsSource':'drawing'}]})
        return {'format':'expectrail.trace/v0','ticks':407,'physicsTicksPerSecond':60,'viewport':[360,640], 'bindings':{'player':{'node':'Paddle'},'ball':{'node':'Ball'}}, 'capabilities':{'roleBoxes':True},'rows':rows}
    def verdict(self, trace):
        from expectrail.gate.verify import observations,window_frames
        from expectrail.evaluator import evaluate
        return evaluate(self.spec,observations(trace,'1'*64),trace=trace,route='auto-input-map',expected_frames=window_frames(self.spec,407,trace,60))
    def test_paddle_moves_in_window_and_tick_zero_cannot_reject_clean_play(self):
        self.assertEqual(self.verdict(self.trace())['result'],'pass')
        bad=self.verdict(self.trace(broken=True));self.assertEqual(bad['result'],'fail');self.assertEqual(bad['firstFrame'],20)
    def test_frozen_paddle_anywhere_cannot_pass_including_in_the_old_left_lane(self):
        for x in (24,36,50.4,80,110.4,168,170.4,300,336):
            with self.subTest(x=x):
                v=self.verdict(self.trace(frozen=x));self.assertEqual(v['result'],'needs-review');self.assertIn('not-reached',v['reason'])
        a,b=self.spec['coverage']['reached']
        # Disjoint permitted balls mean no fixed point (including an unlisted x/y) can satisfy both.
        import math
        self.assertGreater(math.hypot(a['x']-b['x'],a['y']-b['y']),a['tolerancePx']+b['tolerancePx'])
        self.assertTrue(all(self.spec['window']['fromFrame']<=c['tick']<=self.spec['window']['toFrame'] for c in (a,b)))
    def test_drafts_are_unapproved_and_all_three_expected_results_are_explicit(self):
        for p in trial.draft_specs(self.project):self.assertNotIn('approval',json.loads(p.read_text()))
        for p in [self.project]+self.project['changes']:
            self.assertEqual(p['expect'],'needs-review');self.assertEqual(set(p['engineExpect']),{'breakout-paddle-bounds','breakout-ball-starts'})
    def test_diagnostic_replays_require_isolation_in_ci_and_do_not_use_a_model(self):
        checkout=self.root/'checkout';(checkout/'routes').mkdir(parents=True);(checkout/'project').mkdir()
        shutil.copy(ROOT/self.project['routes']/'pointer-auto.json',checkout/'routes')
        calls=[]
        def replay(cmd,**kw):
            calls.append(cmd);dest=Path(cmd[cmd.index('--out')+1]);dest.mkdir(parents=True)
            (dest/'trace.json').write_text(json.dumps(self.trace()));(dest/'replay.json').write_text('{}')
            return subprocess.CompletedProcess(cmd,0,'','')
        with mock.patch.object(trial.subprocess,'run',side_effect=replay):
            findings,summaries=trial.draft_diagnostics(self.project,checkout,self.root/'evidence',10,'isolated')
        self.assertEqual(calls[0][calls[0].index('--sandbox')+1],'require')
        self.assertEqual([f['result'] for f in findings],['pass','pass']);self.assertLess(len(summaries),10)
    def test_missing_ticks_and_refused_capture_never_invent_a_passing_diagnostic(self):
        checkout=self.root/'checkout';(checkout/'routes').mkdir(parents=True);(checkout/'project').mkdir()
        shutil.copy(ROOT/self.project['routes']/'pointer-auto.json',checkout/'routes')
        with mock.patch.object(trial.subprocess,'run',return_value=subprocess.CompletedProcess([],5,'','sandbox unavailable')):
            with self.assertRaisesRegex(trial.TrialError,'exited 5'):trial.draft_diagnostics(self.project,checkout,self.root/'bad',10,'isolated')
        def short(cmd,**kw):
            dest=Path(cmd[cmd.index('--out')+1]);dest.mkdir(parents=True);t=self.trace();t['rows'].pop()
            (dest/'trace.json').write_text(json.dumps(t));(dest/'replay.json').write_text('{}')
            return subprocess.CompletedProcess(cmd,0,'','')
        with mock.patch.object(trial.subprocess,'run',side_effect=short):
            with self.assertRaisesRegex(trial.TrialError,'missing or duplicate ticks'):trial.draft_diagnostics(self.project,checkout,self.root/'short',10,'isolated')
    def test_registry_and_output_examples_validate_with_both_contracts(self):
        from expectrail.contracts import validate
        for kind in ('outside-projects','outside-trial'):
            validate(json.loads((ROOT/f'contracts/examples/{kind}.json').read_text()),kind)
        rows=json.loads((ROOT/'contracts/examples/outside-trial.json').read_text())['projects']
        page=trial.markdown(rows)
        self.assertIn('unapproved',page);self.assertIn('paddle',page);self.assertIn('tick 13',page)

class TrialEnforcementTest(unittest.TestCase):
    def test_main_writes_all_rows_and_fails_on_a_declared_mismatch(self):
        p=copy.deepcopy(trial.load_list()[0]);p['changes']=[];p['expect']='reject'
        row={'name':p['name'],'commit':p['commit'],'licence':p['licence'],'exit':2,'verdict':'needs-review','expect':'reject','checks':None,'reasons':['no vision'],'seconds':1}
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(trial,'load_list',return_value=[p]),mock.patch.object(trial,'lay_out',return_value=Path(tmp)),mock.patch.object(trial,'verify',return_value=row):
            import contextlib,io
            with contextlib.redirect_stdout(io.StringIO()):
                code=trial.main(['--source',tmp,'--out',str(Path(tmp)/'out')])
            self.assertEqual(code,3)
            self.assertTrue((Path(tmp)/'out/outside-trial.json').is_file())
    def test_configured_verification_uses_the_project_path_and_preserves_draft_result(self):
        p=copy.deepcopy(next(p for p in trial.load_list() if p['name']=='breakout'))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);calls=[]
            def command(cmd,**kw):
                calls.append(cmd);return subprocess.CompletedProcess(cmd,2,json.dumps({'decision':'needs-review','reasons':['draft config']}),'')
            diag=[{'spec':name,'result':result} for name,result in p['engineExpect'].items()]
            with mock.patch.object(trial.subprocess,'run',side_effect=command),mock.patch.object(trial,'draft_diagnostics',return_value=(diag,['sweep'])):
                row=trial.verify(p,root/'head',root/'out',['expectrail'],60,'isolated',base=root/'base')
            cmd=calls[0];self.assertIn('--project',cmd);self.assertNotIn('--head',cmd);self.assertNotIn('--specs',cmd)
            self.assertEqual(cmd[cmd.index('--project')+1],str(root/'head/project'))
            self.assertEqual(cmd[cmd.index('--base')+1],str(root/'base/project'))
            self.assertEqual(row['verdict'],'needs-review');self.assertEqual(row['expectationErrors'],[])
    def test_source_config_and_metadata_are_not_silently_overwritten(self):
        p=copy.deepcopy(next(p for p in trial.load_list() if p['name']=='breakout'))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();(source/'project.godot').write_text('config_version=5\n')
            for name in ('routes','checks','expectrail.project.json'):
                marker=source/name;marker.write_text('source content')
                with self.subTest(name=name),self.assertRaisesRegex(trial.TrialError,'overwrite'):
                    trial.lay_out(p,source,root/'out')
                self.assertEqual(marker.read_text(),'source content');marker.unlink()


if __name__=="__main__":unittest.main()
