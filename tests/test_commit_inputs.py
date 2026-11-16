"""Real local Git inputs, offline replay/model stand-ins; no optional image packages."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from expectrail.orchestrator import cli,commits,engines,request,runner,store
from tests import test_ci_gate as gate_cases
from tests import test_two_observers as visual_cases

WATCHED=[]
def no_escape(event,args):
    if event=='open' and WATCHED and isinstance(args[0],(str,bytes,os.PathLike)):
        if os.fsdecode(args[0]) in WATCHED:raise AssertionError('opened a path outside the committed tree')
sys.addaudithook(no_escape)


class CommitInputsTest(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='expectrail-commits-'))
        self.addCleanup(commits.remove_tree,self.root)
        self.repo=gate_cases.make_repo(self.root/'repo',bug=True,routes=('smoke',))
        self.git('init','-q','--initial-branch=main')
        self.git('add','.')
        self.git('commit','-qm','bug base')
        self.base=self.git('rev-parse','HEAD').strip()
        self.git('tag','base')
        (self.repo/'game/platformer/BUG').unlink()
        self.git('add','-A');self.git('commit','-qm','fix')
        self.head=self.git('rev-parse','HEAD').strip()
        self.git('tag','-a','fixed','-m','annotated fixed')
        self.jobs=self.root/'jobs'
        self.model=visual_cases.Game()
        self.engine=engines.GodotGate(replay=self.model.replay,visual=self.model.observer())

    def git(self,*args,data=None):
        env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull)
        result=subprocess.run(['git','-c','user.name=Expectrail test','-c','user.email=test@expectrail.invalid',
             '-c','commit.gpgSign=false','-c','core.hooksPath='+os.devnull,'-C',str(self.repo),*args],
             input=data,capture_output=True,env=env,check=True)
        return result.stdout.decode()

    def run_cli(self,*extra,base='base',head='fixed',folder=False,configured=False):
        def spawn(jobs,job):runner.work(jobs,job,engines={'godot':self.engine})
        args=['verify','--jobs-root',str(self.jobs),'--json']
        if folder:args+=['--head',str(self.repo)]
        else:args+=['--repo',str(self.repo),'--base',base,'--head',head]
        if not configured:args+=['--game','game/platformer','--routes','routes/*.json','--specs','specs']
        args+=list(extra)
        out,err=io.StringIO(),io.StringIO()
        with mock.patch.object(runner,'spawn',side_effect=spawn),contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            code=cli.main(args)
        try:doc=json.loads(out.getvalue())
        except ValueError:doc=None
        return code,doc,err.getvalue()

    def assert_refused(self,phrase,**kw):
        code,doc,err=self.run_cli(**kw)
        self.assertEqual(code,5,(doc,err));self.assertIsNone(doc)
        self.assertIn(phrase,err)
        self.assertEqual(self.model.replays,[])
        self.assertEqual(list((self.jobs/'jobs').glob('*')),[])
        self.assertEqual(list(self.jobs.glob('commit-inputs-*')),[])

    def test_resolves_real_commits_and_judges_own_read_only_copies(self):
        code,doc,err=self.run_cli();self.assertEqual(code,0,err)
        self.assertEqual(doc['decision'],'accept')
        self.assertEqual(doc['inputSources']['head']['commit'],self.head)
        self.assertEqual(doc['inputSources']['base']['commit'],self.base)
        saved=store.JobStore(self.jobs).request(doc['id'])
        for side,want in [('head',self.head),('base',self.base)]:
            path=Path(saved[side]['checkout']);self.assertFalse(path.is_relative_to(self.repo))
            self.assertEqual(saved[side]['commit'],want)
            self.assertFalse((path/'.git').exists())
            for file in [path,*path.rglob('*')]:self.assertFalse(file.stat().st_mode&0o222,file)
            self.assertEqual(doc['inputs'][side+'Tree'],request.tree_digest(path/'game/platformer',path))

    def test_unknown_reference_is_refused(self):self.assert_refused('does not resolve',head='missing-reference')

    def test_equal_resolved_commits_are_refused(self):self.assert_refused('same commit',base='main',head='fixed')

    def test_non_repository_is_refused(self):
        self.repo=self.root/'not-git';self.repo.mkdir()
        self.assert_refused('not a Git repository')

    def test_dirty_HEAD_says_committed_snapshot_is_not_working_tree(self):
        (self.repo/'game/platformer/BUG').touch()
        self.assert_refused('HEAD means committed snapshot',head='HEAD')

    def test_staged_change_with_restored_working_tree_is_dirty_HEAD(self):
        path=self.repo/'game/platformer/BUG';path.touch();self.git('add','-A');path.unlink()
        self.assert_refused('index or working-tree changes',head='HEAD')

    def test_named_commit_ignores_uncommitted_caller_changes(self):
        (self.repo/'game/platformer/BUG').touch()
        code,doc,err=self.run_cli();self.assertEqual((code,doc['decision']),(0,'accept'),err)
        self.assertTrue((self.repo/'game/platformer/BUG').exists())

    def test_ambiguous_real_short_commit_prefix_is_refused(self):
        tree=self.git('rev-parse','HEAD^{tree}').strip();seen={}
        for counter in range(2000):
            body=(f'tree {tree}\nauthor Expectrail <test@expectrail.invalid> 1 +0000\n'
                  f'committer Expectrail <test@expectrail.invalid> 1 +0000\n\n{counter}\n').encode()
            oid=hashlib.sha1(b'commit '+str(len(body)).encode()+b'\0'+body).hexdigest()
            if oid[:4] in seen:
                for data in (seen[oid[:4]],body):self.git('hash-object','-t','commit','-w','--stdin',data=data)
                self.assert_refused('ambiguous short',head=oid[:4]);return
            seen[oid[:4]]=body
        self.fail('deterministic commit-prefix collision was not found')

    def test_ambiguous_branch_and_tag_are_refused(self):
        self.git('branch','ambiguous',self.base);self.git('tag','ambiguous',self.head)
        self.assert_refused('ambiguous reference',head='ambiguous')

    def test_hostile_hooks_filters_and_config_include_do_not_run(self):
        marker=self.root/'executed'
        script=self.root/'poison.sh';script.write_text('#!/bin/sh\ntouch '+str(marker)+'\ncat\n');script.chmod(0o755)
        hook=self.repo/'.git/hooks/post-checkout';shutil.copyfile(script,hook);hook.chmod(0o755)
        # The committed attribute is data; even a force-enabled filter must never run.
        (self.repo/'.gitattributes').write_text('* filter=poison\n')
        self.git('add','.gitattributes');self.git('commit','-qm','attribute data')
        self.git('tag','-f','fixed')
        self.git('config','filter.poison.smudge',str(script));self.git('config','filter.poison.clean',str(script))
        self.git('config','filter.poison.required','true')
        self.git('config','core.fsmonitor',str(script))
        bad=self.root/'included';bad.write_text('invalid git config {{{')
        self.git('config','include.path',str(bad))
        code,doc,err=self.run_cli();self.assertEqual(code,0,err)
        self.assertFalse(marker.exists())
        saved=store.JobStore(self.jobs).request(doc['id'])
        self.assertEqual((Path(saved['head']['checkout'])/'.gitattributes').read_text(),'* filter=poison\n')

    def test_tree_symlink_outside_repository_is_refused_without_reading_target(self):
        target=self.root/'outside';target.write_text('must stay outside')
        (self.repo/'game/platformer/leak').symlink_to(target)
        self.git('add','-A');self.git('commit','-qm','hostile symlink');self.git('tag','-f','fixed')
        WATCHED.append(str(target))
        try:self.assert_refused('symlink')
        finally:WATCHED.clear()
        self.assertEqual(target.read_text(),'must stay outside')

    def test_folder_commit_labels_are_never_reported_as_resolved_commits(self):
        code,doc,err=self.run_cli('--head-commit',self.head,folder=True)
        self.assertEqual(code,0,err)
        self.assertEqual(doc['inputSources']['head'],{'kind':'folder'})
        self.assertIsNone(doc['inputSources']['base'])

    def test_old_examples_and_new_contract_examples_stay_readable(self):
        examples=gate_cases.REPO/'contracts/examples'
        for name in ('verify-request.json','verify-request-commits.json','verify-request-resolved-commits.json'):
            request.load(examples/name)
        for name in ('verify-job.json','verify-job-commits.json'):
            store.check_status(json.loads((examples/name).read_text()))

    def configured_repo(self):
        from tests import test_app_projects as projects
        self.repo=projects.configured_project(self.root/'configured')
        self.git('init','-q','--initial-branch=main')
        (self.repo/'BUG').touch()
        self.git('add','.');self.git('commit','-qm','configured bug')
        self.base=self.git('rev-parse','HEAD').strip();self.git('tag','base')
        (self.repo/'BUG').unlink();self.git('add','-A');self.git('commit','-qm','configured fix')
        self.head=self.git('rev-parse','HEAD').strip();self.git('tag','fixed')

    def test_repo_without_layout_flags_uses_committed_base_config(self):
        self.configured_repo()
        # The caller's uncommitted config is deliberately unusable. Named refs
        # must still use the two committed trees and the base's valid config.
        (self.repo/'expectrail.project.json').write_text('not JSON')
        code,doc,err=self.run_cli(configured=True);self.assertEqual(code,0,err)
        self.assertEqual(doc['decision'],'accept')
        saved=store.JobStore(self.jobs).request(doc['id'])
        self.assertEqual(saved['project']['game'],'project')
        self.assertEqual(saved['commitInputs']['resolved']['base']['commit'],self.base)

    def test_base_config_and_checks_win_over_a_changed_head(self):
        self.configured_repo()
        config=self.repo/'expectrail.project.json';data=json.loads(config.read_text())
        data['approvedContracts']=[];config.write_text(json.dumps(data))
        (self.repo/'BUG').touch();self.git('add','-A');self.git('commit','-qm','head drops policy')
        self.git('tag','-f','fixed')
        code,doc,err=self.run_cli(configured=True)
        self.assertEqual(doc['decision'],'reject',(code,err))
        saved=store.JobStore(self.jobs).request(doc['id'])
        base_config=json.loads((Path(saved['base']['checkout'])/'project/expectrail.project.json').read_text())
        self.assertTrue(base_config['approvedContracts'])

    def test_folder_path_and_commit_path_decide_identically_on_the_same_trees(self):
        code,first,err=self.run_cli();self.assertEqual(code,0,err)
        jobs=store.JobStore(self.jobs);saved=jobs.request(first['id'])
        def spawn(jobs,key):runner.work(jobs,key,engines={'godot':self.engine})
        output=io.StringIO()
        with mock.patch.object(runner,'spawn',side_effect=spawn),contextlib.redirect_stdout(output):
            result=cli.main(['verify','--jobs-root',str(self.jobs),'--json',
                '--base',saved['base']['checkout'],'--head',saved['head']['checkout'],
                '--game','game/platformer','--routes','routes/*.json','--specs','specs'])
        second=json.loads(output.getvalue());self.assertEqual(result,code)
        self.assertEqual(second['decision'],first['decision'])
        self.assertEqual(second['inputs']['headTree'],first['inputs']['headTree'])
        self.assertEqual(second['inputs']['baseTree'],first['inputs']['baseTree'])
        self.assertEqual(second['inputs']['policyDigest'],first['inputs']['policyDigest'])
        from expectrail.gate import record
        findings=[record.read_record(jobs.paths(x['id']).output/'findings.json') for x in (first,second)]
        self.assertEqual(findings[0]['counts'],findings[1]['counts'])
        self.assertEqual(second['inputSources']['head'],{'kind':'folder'})

    def test_forged_resolved_claims_are_discarded_and_resolved_again(self):
        raw=request.build(adapter="godot",head=self.repo,base=self.repo,game='game/platformer',routes=['routes/*.json'],specs='specs')
        raw['commitInputs']={'repository':str(self.repo),'baseRef':'base','headRef':'fixed',
          'resolved':{side:{'commit':'e'*40,'gitTree':'e'*40,'snapshotDigest':'e'*64,'checkout':str(self.repo)}
                      for side in ('head','base')}}
        for side in ('head','base'):raw[side]['commit']='e'*40
        jobs=store.JobStore(self.jobs);status,_=jobs.create(raw)
        self.assertEqual(status['inputSources']['head']['commit'],self.head)
        self.assertEqual(status['inputSources']['base']['commit'],self.base)
        self.assertNotEqual(jobs.request(status['id'])['head']['checkout'],str(self.repo))

    def test_repeated_key_uses_same_pinned_job_and_removes_unused_snapshots(self):
        first=self.run_cli('--idempotency-key','same')[1]
        second=self.run_cli('--idempotency-key','same')[1]
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(list(self.jobs.glob('commit-inputs-*')),[])
        self.assertEqual(len(list((self.jobs/'jobs').iterdir())),1)

    def test_changing_the_repository_after_queue_does_not_change_a_job(self):
        raw=request.build(adapter="godot",head=self.repo,base=self.repo,game='game/platformer',routes=['routes/*.json'],specs='specs')
        raw['commitInputs']={'repository':str(self.repo),'baseRef':'base','headRef':'fixed'}
        jobs=store.JobStore(self.jobs);status,_=jobs.create(raw)
        (self.repo/'game/platformer/BUG').touch();self.git('add','-A');self.git('commit','-qm','later bug')
        self.git('tag','-f','fixed')
        finished=runner.work(jobs,status['id'],engines={'godot':self.engine})
        self.assertEqual(finished['decision'],'accept')
        self.assertEqual(finished['inputSources']['head']['commit'],self.head)

    def test_tampered_origin_in_a_job_is_refused_by_the_reader(self):
        raw=request.build(adapter="godot",head=self.repo,game='game/platformer',routes=['routes/*.json'],specs='specs',head_commit=self.head)
        jobs=store.JobStore(self.jobs);status,_=jobs.create(raw)
        self.assertIsNone(jobs.request(status['id'])['head']['commit'])
        status['inputSources']['head']={'kind':'commit','repository':str(self.repo),'ref':'fixed',
            'commit':self.head,'gitTree':'a'*40,'snapshotDigest':'b'*64}
        jobs.paths(status['id']).status.write_text(json.dumps(status))
        with self.assertRaisesRegex(store.StoreError,'origins differ'):jobs.status(status['id'])

    def test_clean_HEAD_ignores_ignored_files_without_running_filters(self):
        (self.repo/'.gitignore').write_text('ignored.tmp\n')
        self.git('add','.gitignore');self.git('commit','-qm','ignore local output')
        (self.repo/'ignored.tmp').write_text('local data')
        code,doc,err=self.run_cli(head='HEAD');self.assertEqual(code,0,err)
        self.assertEqual(doc['decision'],'accept')

    def test_clean_HEAD_is_checked_before_creating_an_inside_job_store(self):
        self.jobs=self.repo/'runs/jobs'
        code,doc,err=self.run_cli(head='HEAD')
        self.assertEqual(code,0,err)
        self.assertEqual(doc['inputSources']['head']['commit'],self.head)
        self.assertEqual(doc['decision'],'accept')
        self.assertEqual(self.git('rev-parse','HEAD').strip(),self.head)

    def test_submodule_is_refused_without_fetch(self):
        self.git('update-index','--add','--cacheinfo','160000,'+self.head+',external')
        self.git('commit','-qm','submodule entry');self.git('tag','-f','fixed')
        self.assert_refused('submodule fetching is disabled')

    def test_packed_objects_are_read_without_checkout(self):
        self.git('gc','--prune=now')
        code,doc,err=self.run_cli();self.assertEqual(code,0,err)
        self.assertEqual(doc['inputSources']['head']['commit'],self.head)

    def test_sha256_repository_resolves_full_ids_and_trees(self):
        shutil.rmtree(self.repo/'.git')
        (self.repo/'game/platformer/BUG').touch()
        self.git('init','-q','--initial-branch=main','--object-format=sha256')
        self.git('add','.');self.git('commit','-qm','SHA256 base')
        self.base=self.git('rev-parse','HEAD').strip();self.git('tag','base')
        (self.repo/'game/platformer/BUG').unlink()
        self.git('add','-A');self.git('commit','-qm','SHA256 head')
        self.head=self.git('rev-parse','HEAD').strip();self.git('tag','fixed')
        code,doc,err=self.run_cli();self.assertEqual(code,0,err)
        self.assertEqual(doc['inputSources']['head']['commit'],self.head)
        self.assertEqual(len(doc['inputSources']['base']['commit']),64)
        self.assertEqual(len(doc['inputSources']['head']['gitTree']),64)

    def test_public_command_resolves_before_starting_a_worker(self):
        result=subprocess.run([sys.executable,'-m','expectrail.cli','verify',
            '--repo',str(self.repo),'--base','base','--head','missing-reference',
            '--game','game/platformer','--routes','routes/*.json','--specs','specs',
            '--jobs-root',str(self.jobs),'--json'],capture_output=True,text=True)
        self.assertEqual(result.returncode,5,result.stderr)
        self.assertIn('does not resolve',result.stderr)
        self.assertEqual(list((self.jobs/'jobs').glob('*')),[])

    def test_linked_worktree_and_bare_repository_are_supported(self):
        linked=self.root/'linked';self.git('worktree','add','--detach',str(linked),'fixed')
        original=self.repo;self.repo=linked
        first=self.run_cli()[1];self.assertEqual(first['decision'],'accept')
        bare=self.root/'bare'
        subprocess.run(['git','-c','core.hooksPath='+os.devnull,'clone','--bare','--local',
                        str(original),str(bare)],capture_output=True,check=True)
        self.repo=bare
        code,doc,err=self.run_cli(head='HEAD');self.assertEqual(code,0,err)
        self.assertEqual(doc['inputSources']['head']['commit'],self.head)

    def test_git_environment_and_replace_refs_cannot_change_commit_identity(self):
        self.git('replace',self.head,self.base)
        with mock.patch.dict(os.environ,{'GIT_DIR':str(self.root/'wrong'),
                'GIT_WORK_TREE':str(self.root/'wrong'),'GIT_OBJECT_DIRECTORY':str(self.root/'wrong'),
                'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'core.fsmonitor','GIT_CONFIG_VALUE_0':'false'}):
            code,doc,err=self.run_cli()
        self.assertEqual(code,0,err)
        self.assertEqual(doc['inputSources']['head']['commit'],self.head)

    def test_missing_promisor_object_does_not_contact_a_remote(self):
        import http.server
        import threading
        hits=[]
        class Server(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path);self.send_response(404);self.end_headers()
            def log_message(self,*_):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Server)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        oid=self.git('rev-parse','fixed:game/platformer/project.godot').strip()
        (self.repo/'.git/objects'/oid[:2]/oid[2:]).unlink()
        self.git('config','extensions.partialClone','origin')
        self.git('config','remote.origin.promisor','true')
        self.git('config','remote.origin.url',f'http://127.0.0.1:{server.server_port}/repo')
        self.assert_refused('local Git object is missing')
        self.assertEqual(hits,[])

    def test_changed_retained_snapshot_stops_before_replay(self):
        raw=request.build(adapter='godot',head=self.repo,base=self.repo,game='game/platformer',routes=['routes/*.json'],specs='specs')
        raw['commitInputs']={'repository':str(self.repo),'baseRef':'base','headRef':'fixed'}
        jobs=store.JobStore(self.jobs);status,_=jobs.create(raw)
        saved=jobs.request(status['id']);path=Path(saved['head']['checkout'])/'game/platformer/project.godot'
        path.chmod(0o644);path.write_text('changed after preparation')
        finished=runner.work(jobs,status['id'],engines={'godot':self.engine})
        self.assertEqual(finished['decision'],'needs-review')
        self.assertEqual(self.model.replays,[])
        self.assertIn('snapshot',str(finished['reasons']))
