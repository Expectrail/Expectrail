"""Prepare/publish a draft from an authenticated repair artifact, as data only.

No candidate checkout, game, installer, shell, fixer or model runs. The only Git
commands operate on a fresh temporary index. Publishing is explicit and draft-only.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import urllib.parse
import urllib.request
import urllib.error
import zipfile

from expectrail import contracts, viewer
from expectrail.gate import record
from harness import tree
from tools import ci_autofix, ci_checks

WORKFLOW = '.github/workflows/expectrail-autofix.yml'
LIMIT = 8*1024*1024


class NoAcceptedRepair(ValueError):
    pass


class PreparedPlan(dict):
    """In-memory witness from prepare, never instantiated from an artifact JSON."""


def safe(name):
    if (not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_./-]+',name)
            or name.startswith('/') or any(p in ('', '.', '..', '.git', '.github', '.env', 'specs', 'routes')
            or p.startswith(('fresh-', 'blind-', 'expectrail.')) or p == 'AGENTS.md' for p in name.split('/'))):
        raise ValueError('patch path is outside the allowed game-data scope')
    return name


def sha(raw): return hashlib.sha256(raw).hexdigest()
def blob(raw): return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def repository_name(repo):
    if (not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo)
            or any(part in ('.', '..') for part in repo.split('/'))):
        raise ValueError('invalid repository')
    return repo


def authorize(api, repo, number, run_id, app_id):
    repository_name(repo)
    root='/repos/'+repo
    repository=api('GET',root)
    pr=api('GET',root+f'/pulls/{int(number)}')
    run=api('GET',root+f'/actions/runs/{int(run_id)}')
    if (run['path'] != WORKFLOW or run['event'] != 'pull_request' or run['conclusion'] != 'success'
            or run['head_sha'] != pr['head']['sha'] or run['head_repository']['full_name'] != pr['head']['repo']['full_name']
            or run['head_branch'] != pr['head']['ref'] or pr['state'] != 'open'
            or pr['base']['ref'] != repository['default_branch']):
        raise ValueError('repair run is not a successful current-head labelled-PR run')
    recent=api('GET',root+f"/actions/workflows/{int(run['workflow_id'])}/runs?event=pull_request&head_sha={run['head_sha']}&per_page=100")['workflow_runs']
    if not recent or max((r['id'],r['run_attempt']) for r in recent) != (run['id'],run['run_attempt']):
        raise ValueError('repair attempt is no longer the latest')
    revisions=((repo,pr['base']['sha']),(repo,pr['merge_commit_sha']),
               (pr['head']['repo']['full_name'],pr['head']['sha']))
    workflows=[api('GET',f'/repos/{r}/contents/{WORKFLOW}?ref={ref}') for r,ref in revisions]
    if any(w['type']!='file' for w in workflows) or len({w['sha'] for w in workflows}) != 1:
        raise ValueError('repair workflow differs from the trusted base')
    event={'action':'labeled','label':{'name':'expectrail-autofix'},'pull_request':pr,
           'repository':{'full_name':repo,'default_branch':repository['default_branch']},
           'sender':{'login':run['actor']['login']}}
    ci_autofix.published_reject(event,app_id,lambda p:api('GET',p),lambda p:api('GET',p))
    return pr,run


def artifact(api,repo,run):
    name=f"expectrail-repair-{run['id']}-{run['run_attempt']}"
    listing=api('GET',f"/repos/{repo}/actions/runs/{run['id']}/artifacts?name={name}")
    matches=[a for a in listing['artifacts'] if a['name']==name and not a['expired']]
    if len(matches)!=1 or not 0 < matches[0]['size_in_bytes'] <= LIMIT:
        raise ValueError('expected one small immutable repair artifact')
    item=matches[0]
    if not re.fullmatch(r'sha256:[0-9a-f]{64}',item.get('digest','')):raise ValueError('artifact has no GitHub digest')
    return item


def unpack(archive, target, item):
    raw=record.read_bytes_capped(archive,LIMIT,'repair artifact')
    if len(raw)!=item['size_in_bytes'] or 'sha256:'+sha(raw)!=item['digest']:
        raise ValueError('artifact differs from its GitHub digest')
    with zipfile.ZipFile(archive) as source:
        entries=source.infolist();names=set()
        if len(entries)>32 or sum(e.file_size for e in entries)>LIMIT:raise ValueError('artifact extraction cap')
        for entry in entries:
            name=entry.orig_filename
            if entry.is_dir():
                if not re.fullmatch(r'attempt-[0-9]{1,2}/',name):raise ValueError('unexpected archive directory')
                continue
            if (name in names or not re.fullmatch(r'(repair-run\.json|attempt-[0-9]{1,2}/(candidate\.patch|fixer-invocation\.json))',name)
                    or entry.file_size>2*1024*1024 or entry.flag_bits&1
                    or stat.S_IFMT(entry.external_attr>>16) not in (0,stat.S_IFREG)):
                raise ValueError('unexpected, linked or duplicate repair artifact member')
            names.add(name);path=target/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(source.read(entry))


def apply_data(files, patch):
    """No worktree or filters: git apply changes an isolated index of regular blobs."""
    if len(patch)>1024*1024:raise ValueError('patch exceeds cap')
    text=patch.decode('utf-8')
    if any(word in text for word in ('GIT binary patch','rename from ','rename to ','copy from ','copy to ')):
        raise ValueError('only bounded text edits, additions and deletions are published')
    with tempfile.TemporaryDirectory(prefix='expectrail-patch-data-') as tmp:
        root=Path(tmp);env={'PATH':os.defpath,'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,
                            'GIT_INDEX_FILE':str(root/'index')}
        def git(*args,input=None):
            return subprocess.check_output(['git','--git-dir='+str(root/'objects'),*args],input=input,env=env,stderr=subprocess.PIPE)
        git('init','--bare','--quiet',str(root/'objects'));git('read-tree','--empty')
        for name,(mode,raw) in files.items():
            oid=git('hash-object','-w','--stdin',input=raw).decode().strip()
            git('update-index','--add','--cacheinfo',mode+','+oid+','+safe(name))
        stats=git('apply','--numstat','-z',input=patch).decode().split('\0')
        touched=[]
        for row in filter(None,stats):
            a,b,name=row.split('\t');safe(name)
            if not a.isdigit() or not b.isdigit():raise ValueError('binary patch refused')
            touched.append(name)
        if not touched or len(set(touched))!=len(touched):raise ValueError('empty or ambiguous patch')
        patch_file=root/'candidate.patch';patch_file.write_bytes(patch)
        from agents.export_scan import scan
        if any(f['level']=='error' for f in scan([patch_file],paths_level='error')):raise ValueError('patch failed export scan')
        git('apply','--cached','--whitespace=nowarn','-',input=patch)
        result={}
        for row in filter(None,git('ls-files','--stage','-z').decode().split('\0')):
            meta,name=row.split('\t');mode,oid,stage=meta.split()
            if mode not in ('100644','100755') or stage!='0':raise ValueError('patch introduced a link or conflict')
            raw=git('cat-file','blob',oid)
            if name in touched and name.endswith('.json'):
                try:doc=json.loads(raw)
                except ValueError:doc=None
                if isinstance(doc,dict) and (str(doc.get('format','')).startswith('expectrail.') or 'approval' in doc):
                    raise ValueError('patch changes verifier policy, not game data')
            result[name]=(mode,raw)
        return {name:result.get(name) for name in touched if result.get(name)!=files.get(name)}


def prepare(api, repo, number, run_id, app_id, archive, *, game):
    safe(game)
    pr,run=authorize(api,repo,number,run_id,app_id);item=artifact(api,repo,run)
    with tempfile.TemporaryDirectory(prefix='expectrail-draft-data-') as tmp:
        root=Path(tmp);unpack(Path(archive),root,item)
        opened=viewer.read_repair(root/'repair-run.json');doc=opened['run']
        if doc['result']['decision']!='accept' or opened['diff'] is None:raise NoAcceptedRepair('recorded repair needs review; no draft was created')
        if any(a.get('advisoryDiscovery') or a.get('gateDecision',a['decision'])!=a['decision'] for a in doc['attempts']):
            raise ValueError('repair has a review flag')
        if doc['fixer']['source']=='llm-patch':
            from expectrail.repair_provenance import provider_only
            provider_only(root/'repair-run.json',doc)
        head_repo=pr['head']['repo']['full_name'];prefix=f'/repos/{head_repo}'
        commit=api('GET',prefix+'/git/commits/'+pr['head']['sha'])
        listing=api('GET',prefix+'/git/trees/'+commit['tree']['sha']+'?recursive=1')
        if listing['truncated'] or len(listing['tree'])>100000:raise ValueError('head tree is incomplete')
        game_root=root/'game';game_root.mkdir();files={};size=0
        for row in listing['tree']:
            if not row['path'].startswith(game+'/') or row['type']=='tree':continue
            name=safe(row['path'][len(game)+1:])
            if row['mode'] not in ('100644','100755') or row['type']!='blob':raise ValueError('game contains a link')
            encoded=api('GET',prefix+'/git/blobs/'+row['sha'])
            if encoded['encoding']!='base64':raise ValueError('unsupported blob encoding')
            raw=base64.b64decode(encoded['content'],validate=False);size+=len(raw)
            if size>64*1024*1024:raise ValueError('game data cap exceeded')
            if blob(raw)!=row['sha']:raise ValueError('head blob digest differs')
            path=game_root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            files[name]=(row['mode'],raw)
        if tree.digest(game_root,within=game_root,skip=tree.GODOT_SKIP)!=doc['parent']['headTree']:
            raise ValueError('repair parent differs from the current head game')
        changes=apply_data(files,opened['diff'].encode())
        if not changes:raise ValueError('patch has no game changes')
        plan={'format':'expectrail.repair-publication/v1','repository':repo,'pullRequest':int(number),
              'run':int(run_id),'attempt':run['run_attempt'],'baseSha':pr['base']['sha'],'headSha':pr['head']['sha'],
              'baseBranch':pr['base']['ref'],'headTree':commit['tree']['sha'],'game':game,
              'artifactSha256':item['digest'][7:],'recordSha256':sha((root/'repair-run.json').read_bytes()),
              'patchSha256':sha(opened['diff'].encode()),'fixerSource':doc['fixer']['source'],
              'changes':[{'path':game+'/'+n,'mode':v[0] if v else '100644',
                          'content':base64.b64encode(v[1]).decode() if v else None} for n,v in sorted(changes.items())]}
        check(plan)
        result=PreparedPlan(plan);result.witness=contracts.digest(plan)
        return result


def check(plan):
    contracts.validate_v1(plan,'repair-publication');safe(plan['game'])
    repository_name(plan['repository'])
    paths=[];size=0
    for row in plan['changes']:
        safe(row['path']);paths.append(row['path'])
        if not row['path'].startswith(plan['game']+'/'):raise ValueError('plan leaves game')
        if row['content'] is not None:size+=len(base64.b64decode(row['content'],validate=True))
    if len(set(paths))!=len(paths) or size>LIMIT:raise ValueError('plan changes exceed bounds')
    return plan


def publish(plan, api, *, app_id):
    check(plan)
    if not isinstance(plan,PreparedPlan) or plan.witness != contracts.digest(plan):
        raise ValueError("publication requires an unchanged plan from authenticated preparation")
    repo=plan['repository'];root='/repos/'+repo
    def current():
        pr,run=authorize(api,repo,plan['pullRequest'],plan['run'],app_id)
        if (pr['head']['sha'],pr['base']['sha'],run['run_attempt']) != (plan['headSha'],plan['baseSha'],plan['attempt']):
            raise ValueError('plan is stale')
        item=artifact(api,repo,run)
        if item['digest'] != 'sha256:'+plan['artifactSha256']: raise ValueError('artifact changed')
        return pr
    # Regenerate the plan from its authenticated artifact before invoking this
    # API function (CLI does so); this is a trusted in-memory plan, not PR text.
    current();entries=[]
    branch=f"expectrail/fix-{plan['pullRequest']}-{plan['headSha'][:12]}-{plan['run']}-{plan['attempt']}"
    if api('GET',root+'/git/ref/heads/'+branch) is not None:raise ValueError('repair branch already exists; inspect it, never overwrite')
    if api('GET',root+'/pulls?state=all&head='+urllib.parse.quote(repo.split('/')[0]+':'+branch,safe='')):
        raise ValueError('repair PR already exists')
    def post(path, body):current();return api('POST',root+path,body)
    for row in plan['changes']:
        oid=None
        if row['content'] is not None:
            raw=base64.b64decode(row['content'],validate=True)
            made=post('/git/blobs',{'encoding':'base64','content':row['content']})
            if made['sha']!=blob(raw):raise ValueError('published blob differs')
            oid=made['sha']
        entries.append({'path':row['path'],'mode':row['mode'],'type':'blob','sha':oid})
    made=post('/git/trees',{'base_tree':plan['headTree'],'tree':entries})
    commit=post('/git/commits',{'message':'Expectrail repair candidate '+plan['patchSha256'],
        'tree':made['sha'],'parents':[plan['headSha']]})
    post('/git/refs',{'ref':'refs/heads/'+branch,'sha':commit['sha']})
    result=post('/pulls',{'title':f"Expectrail repair candidate for #{plan['pullRequest']}",
        'head':branch,'base':plan['baseBranch'],'draft':True,'maintainer_can_modify':False,
        'body':f"Machine-written {plan['fixerSource']} candidate; accepted on the recorded approved checks; review before merging.\n\nOriginal PR #{plan['pullRequest']}, head {plan['headSha']}.\nRepair run {plan['run']}, attempt {plan['attempt']}.\nArtifact SHA-256: {plan['artifactSha256']}\nPatch SHA-256: {plan['patchSha256']}\n\nNothing was merged. Fixture/recorded sources are offline examples, not live fixer measurements."})
    if not result.get('draft'):raise ValueError('GitHub did not create a draft')
    return result


def http_api(token):
    opener=urllib.request.build_opener(ci_checks.NoRedirect)
    def call(method,path,body=None):
        data=json.dumps(body).encode() if body is not None else None
        req=urllib.request.Request('https://api.github.com'+path,data=data,method=method,headers={
            'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
            'Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28'})
        try:
            with opener.open(req,timeout=30) as response:raw=response.read(LIMIT+1)
        except urllib.error.HTTPError as exc:
            if method=='GET' and exc.code==404:return None
            raise ValueError('GitHub refused the publisher request (HTTP '+str(exc.code)+')') from None
        if len(raw)>LIMIT:raise ValueError('GitHub response exceeds cap')
        return record.strict_loads(raw.decode()) if raw else None
    return call


def resolve_number(api,repo,run_id):
    repository_name(repo)
    run=api('GET',f'/repos/{repo}/actions/runs/{run_id}')
    if not run or not re.fullmatch('[0-9a-f]{40}',run.get('head_sha','')):raise ValueError('invalid repair run')
    prs=api('GET',f"/repos/{repo}/commits/{run['head_sha']}/pulls?per_page=100")
    candidates=[p for p in prs if p['state']=='open' and p['head']['sha']==run['head_sha']
                and p['head']['repo']['full_name']==run['head_repository']['full_name']
                and p['head']['ref']==run['head_branch']]
    if len(candidates)!=1:raise ValueError('repair run does not identify one current pull request')
    return candidates[0]['number']


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('repo','run','app-id','out'):p.add_argument('--'+name,required=True)
    p.add_argument('--pr',type=int)
    p.add_argument('--game',default='game/platformer');p.add_argument('--send',action='store_true')
    args=p.parse_args(argv)
    token=os.environ.get('GITHUB_TOKEN','')
    if not token:raise ValueError('publisher needs a scoped GitHub token; never put it in an input')
    api=http_api(token)
    # A trusted workflow downloads only the authenticated run artifact. No
    # candidate code executes in this process or its job.
    number=args.pr if args.pr is not None else resolve_number(api,args.repo,int(args.run))
    pr,run=authorize(api,args.repo,number,int(args.run),int(args.app_id))
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    ci_checks.download(api,SimpleNamespace(repo=args.repo,run_id=int(args.run)),run,out/'repair.zip',token,
                       artifact_name=f"expectrail-repair-{run['id']}-{run['run_attempt']}",max_bytes=LIMIT)
    try:
        plan=prepare(api,args.repo,number,int(args.run),int(args.app_id),out/'repair.zip',game=args.game)
    except NoAcceptedRepair as exc:
        print(str(exc));return 0
    (out/'plan.json').write_bytes(contracts.canonical_v1(plan)+b'\n')
    if args.send:
        result=publish(plan,api,app_id=int(args.app_id));(out/'draft.json').write_text(json.dumps(result,indent=2)+'\n')
    return 0


if __name__=='__main__':raise SystemExit(main())
