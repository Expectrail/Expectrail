"""Draft publisher runs against a GitHub stand-in, never the network."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from expectrail import contracts
from harness import tree
from tests.test_ci_gate import BASE, HEAD
from tools import ci_autofix, ci_checks


class DraftPublisher(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root = Path(tmp.name)
        self.game = self.root/'game'; self.game.mkdir(); (self.game/'player.gd').write_text('broken\n')
        self.pr = {'number':8,'state':'open','base':{'sha':BASE,'ref':'main'},
                   'head':{'sha':HEAD,'repo':{'full_name':'org/game'},'ref':'change'},
                   'labels':[{'name':'expectrail-autofix'}], 'merge_commit_sha':'3'*40}
        self.run = {'id':45,'run_attempt':1,'workflow_id':5,'head_sha':HEAD,
                    'path':'.github/workflows/expectrail-autofix.yml','event':'pull_request',
                    'head_repository':{'full_name':'org/game'},'head_branch':'change',
                    'conclusion':'success','actor':{'login':'sean'}, 'pull_requests':[self.pr]}
        self.calls=[]; self.move_after_write=False; self.workflow_changed=False
        self.archive = self.root/'artifact.zip'
        self.patch = b'--- a/player.gd\n+++ b/player.gd\n@@ -1 +1 @@\n-broken\n+fixed\n'
        doc=json.loads((Path(__file__).resolve().parents[1]/'contracts/examples/repair-run.v1.json').read_text())
        doc['parent']['headTree']=tree.digest(self.game,within=self.game)
        doc['attempts'][0]['patchSha256']=hashlib.sha256(self.patch).hexdigest()
        self.old_blob=hashlib.sha1(b'blob 7\0broken\n').hexdigest()
        self.doc=doc; self.pack()

    def pack(self):
        with zipfile.ZipFile(self.archive,'w') as z:
            z.writestr('repair-run.json',json.dumps(self.doc))
            z.writestr('attempt-1/candidate.patch',self.patch)
        raw=self.archive.read_bytes()
        self.artifact_meta={'id':90,'name':'expectrail-repair-45-1','expired':False,'size_in_bytes':len(raw),'digest':'sha256:'+hashlib.sha256(raw).hexdigest()}

    def api(self, method, path, body=None):
        self.calls.append((method,path,body))
        if method=='GET':
            if path=='/repos/org/game':return {'default_branch':'main'}
            if path.endswith('/pulls/8'):return copy.deepcopy(self.pr)
            if '/collaborators/' in path:return {'permission':'write'}
            if '/check-runs?' in path:return {'total_count':1,'check_runs':[{'head_sha':HEAD,'name':ci_checks.CLEARANCE,'app':{'id':73},'external_id':'expectrail/12/1','status':'completed','conclusion':'failure','output':{'summary':'reject'}}]}
            if path.endswith('/actions/runs/12/attempts/1'):
                return self.run|{'id':12,'path':ci_checks.CALLER}
            if path.endswith('/actions/runs/45'):return copy.deepcopy(self.run)
            if '/actions/workflows/' in path:return {'workflow_runs':[copy.deepcopy(self.run)]}
            if '/contents/.github/workflows/' in path:
                return {'type':'file','sha':('4' if self.workflow_changed and 'ref='+HEAD in path else '5')*40}
            if '/artifacts?' in path:
                return {'artifacts':[copy.deepcopy(self.artifact_meta)]}
            if '/git/commits/' in path:return {'sha':HEAD,'tree':{'sha':'6'*40}}
            if '/git/trees/' in path:return {'truncated':False,'tree':[{'path':'game/player.gd','mode':'100644','type':'blob','sha':self.old_blob}]}
            if '/git/blobs/' in path:return {'encoding':'base64','content':base64.b64encode(b'broken\n').decode()}
            if '/git/ref/' in path:return None
            if '/pulls?' in path:return []
            raise AssertionError(path)
        self.assertEqual(method,'POST')
        if self.move_after_write:self.pr['head']['sha']='8'*40
        if path.endswith('/git/blobs'):
            raw=base64.b64decode(body['content']);return {'sha':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
        if path.endswith('/git/trees'):return {'sha':'9'*40}
        if path.endswith('/git/commits'):return {'sha':'a'*40}
        if path.endswith('/git/refs'):return {'ref':body['ref'],'object':{'sha':body['sha']}}
        if path.endswith('/pulls'):return {'number':99,'draft':True,'html_url':'https://github.com/org/game/pull/99'}
        raise AssertionError(path)

    def prepare(self):
        from tools import repair_draft
        return repair_draft.prepare(self.api,'org/game',8,45,73,self.archive,game='game')

    def test_plan_runs_only_data_git_commands_and_publication_is_draft_only(self):
        plan=self.prepare()
        self.assertFalse(any(m!='GET' for m,_,_ in self.calls))
        from tools import repair_draft
        result=repair_draft.publish(plan,self.api,app_id=73)
        self.assertTrue(result['draft'])
        post=[(p,b) for m,p,b in self.calls if m=='POST']
        self.assertTrue(post[-1][1]['draft'])
        self.assertFalse(any('/merge' in p or m in ('PUT','PATCH') for m,p,_ in self.calls))
        self.assertIn('fixture',post[-1][1]['body'])

    def test_changed_head_or_workflow_or_tampered_artifact_sends_no_write(self):
        self.workflow_changed=True
        with self.assertRaises(ValueError):self.prepare()
        self.workflow_changed=False
        plan=self.prepare(); self.pr['head']['sha']='8'*40
        from tools import repair_draft
        with self.assertRaises(ValueError):repair_draft.publish(plan,self.api,app_id=73)
        self.assertFalse(any(m!='GET' for m,_,_ in self.calls))

    def test_head_moved_mid_publication_never_opens_a_pr(self):
        plan=self.prepare();self.move_after_write=True
        from tools import repair_draft
        with self.assertRaises(ValueError):repair_draft.publish(plan,self.api,app_id=73)
        self.assertFalse(any(m=='POST' and p.endswith('/pulls') for m,p,_ in self.calls))

    def test_rejected_flagged_or_out_of_scope_patch_is_never_published(self):
        original=copy.deepcopy(self.doc);patch=self.patch
        for change in ('review','scope','flag'):
            self.doc=copy.deepcopy(original);self.patch=patch
            if change=='review':self.doc['result']['decision']='needs-review'
            elif change=='scope':self.patch=b'--- a/../policy.json\n+++ b/../policy.json\n@@ -1 +1 @@\n-a\n+b\n'
            else:self.doc['attempts'][0]['advisoryDiscovery']=['look']
            self.doc['attempts'][0]['patchSha256']=hashlib.sha256(self.patch).hexdigest();self.pack()
            with self.assertRaises((ValueError,contracts.ContractError) if hasattr(contracts,'ContractError') else ValueError):self.prepare()
        self.assertFalse(any(m!='GET' for m,_,_ in self.calls))

    def test_changed_plan_or_archive_is_not_a_publication_authority(self):
        from tools import repair_draft
        plan=self.prepare();plan['changes'][0]['content']=base64.b64encode(b'other\n').decode()
        with self.assertRaises(ValueError):repair_draft.publish(plan,self.api,app_id=73)
        with self.assertRaises(ValueError):repair_draft.publish(dict(self.prepare()),self.api,app_id=73)
        self.archive.write_bytes(self.archive.read_bytes()+b'tamper')
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(any(m!='GET' for m,_,_ in self.calls))

    def test_repository_path_cannot_escape_api_scope_even_during_resolution(self):
        from tools import repair_draft
        for name in ('../game', 'org/..', 'org/game/extra', '/org/game'):
            with self.assertRaises(ValueError): repair_draft.resolve_number(self.api,name,45)
        self.assertEqual(self.calls,[])

    def test_real_entry_point_prepares_by_default_and_send_is_explicit(self):
        from tools import repair_draft
        import os
        def download(api,ctx,run,path,token,**kw):
            self.assertEqual(kw,{'artifact_name':'expectrail-repair-45-1','max_bytes':repair_draft.LIMIT})
            path.write_bytes(self.archive.read_bytes())
        with mock.patch.object(repair_draft,'http_api',return_value=self.api), \
             mock.patch.object(ci_checks,'download',side_effect=download), \
             mock.patch.dict(os.environ,{'GITHUB_TOKEN':'offline-only'}):
            args=['--repo','org/game','--pr','8','--run','45','--app-id','73','--game','game']
            self.assertEqual(repair_draft.main(args+['--out',str(self.root/'plan')]),0)
            self.assertFalse(any(m!='GET' for m,_,_ in self.calls))
            contracts.load_strict(self.root/'plan/plan.json','repair-publication')
            self.assertEqual(repair_draft.main(args+['--out',str(self.root/'send'),'--send']),0)
        self.assertTrue(json.loads((self.root/'send/draft.json').read_text())['draft'])


class WorkflowProposal(unittest.TestCase):
    def test_privileged_job_reads_only_main_and_data_and_has_no_model_key(self):
        import yaml
        root=Path(__file__).resolve().parents[1]
        proposed=yaml.safe_load((root/'docs/proposals/433-draft-publisher.yml.txt').read_text())
        triggers=proposed.get('on',proposed.get(True))
        self.assertEqual(set(triggers),{'workflow_run','workflow_dispatch'})
        job=proposed['jobs']['publish']
        self.assertEqual(job['permissions'],{'contents':'write','pull-requests':'write','actions':'read'})
        self.assertIn("refs/heads/main",job['if'])
        self.assertEqual(job['steps'][0]['with']['ref'],'main')
        self.assertFalse(job['steps'][0]['with']['persist-credentials'])
        steps=json.dumps(job['steps']).lower()
        for forbidden in ('godot','harness','xvfb','model_api_key','fixer_api_key','head_repository','head_sha'):
            self.assertNotIn(forbidden,steps)
        self.assertEqual(sum('GITHUB_TOKEN' in s.get('env',{}) for s in job['steps']),1)
        installed=root/'.github/workflows/expectrail-repair-draft.yml'
        if installed.exists():self.assertEqual(yaml.safe_load(installed.read_text()),proposed)
