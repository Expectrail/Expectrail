"""Manual, public-only #271 pressure runs. Default is a plan; never auto-dispatch.

Frozen, authenticated counting checks are prerequisites, not generated here.
Correct pressure covers every exact undo in the 24-defect public registry, plus
all registered correct known-bench patches. The adversary is one attempt on the
public air-jump bug; only that test intentionally gives its fixer the checks.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from expectrail.contracts import digest_v1, validate
from expectrail.gate import record
from expectrail.jit import counting
from expectrail.jit.run import _evaluate
from expectrail.jit import bench
from expectrail.trace.normalize import from_run_dir

REPO=Path(__file__).resolve().parents[2]
MODEL='gpt-6.1-sol'
API_CAP='6.00'


class Stop(RuntimeError):pass


class Replays:
    def __init__(self, cap, runner=None):
        if type(cap) is not int or not 0<cap<=1024:raise ValueError('replay cap must be 1..1024')
        self.cap,self.used,self.runner=cap,0,runner
    def run(self, route, out, patches):
        if self.used>=self.cap:raise Stop('replay-cap: nothing further replayed')
        self.used+=1
        if self.runner is None:
            from harness.run import run
            return run(route,out,patches=patches,capture_frames=False,sandbox='require')
        return self.runner(route,out,patches=patches,sandbox='require')


def frozen(folder, trust):
    if bench.private_name(folder):raise Stop('public-only: held-out/fresh names refused')
    envelope=record.read_json(folder/'generated-counting.json',cap=8*1024*1024)
    proof=counting.read(envelope,trust=trust)
    counted={r['specId'] for r in proof.block['rows'] if record.counting_row(r)}
    if not counted:raise Stop('no-counting-checks: no fixer or model may start')
    run=envelope['sourceRun'];entries=[p for p in run['proposed'] if p['spec']['id'] in counted]
    digests={p['id']:p['routeSha256'] for p in run['probes']};routes={}
    for pid in sorted({pid for p in entries for pid in p['probeIds']}):
        path=folder/'jit-routes'/('jit-'+pid.removeprefix('jit-')+'.json')
        if not path.resolve().is_relative_to(folder.resolve()):raise Stop('route path escapes frozen bundle')
        route=record.read_json(path,cap=1024*1024);validate(route,'route')
        if digest_v1(route)!=digests[pid]:raise Stop('route-digest-mismatch')
        routes[pid]=route
    return envelope,entries,routes


def judge_candidate(entries,routes,patches,out,replays):
    path=Path(out);path.mkdir(parents=True,exist_ok=True)
    values={p['spec']['id']:[] for p in entries}
    for rep in range(3):
        eps={}
        for pid,route in routes.items():
            route_file=path/(pid.replace('/','-')+'.json');route_file.write_text(json.dumps(route))
            destination=path/f'run-{rep}'/pid
            replays.run(route_file,destination,patches)
            eps[pid]=from_run_dir(destination,route,episode_id=f'{pid}-{rep}')
        for entry in entries:values[entry['spec']['id']].append(_evaluate(entry,entry['probeIds'],eps))
    return values


def pressure_status(rows, expected):
    # A single failure on a known correct fix blocks release, even if a flaky
    # result would have dropped it from counting in a fresh generation run.
    if any('fail' in r['outcomes'] for r in rows):return 'failed'
    if len({r['case'] for r in rows})!=expected or not rows or any(r['outcomes']!=['pass']*3 for r in rows):return 'blocked'
    return 'complete'


def calibrated(clean, bug):
    return (len(clean)==len(bug)==3 and all(type(n) is int and n>=0 for n in clean+bug)
            and len(set(clean))==len(set(bug))==1 and bug[0]>clean[0])


def adversary_succeeded(rows, values):
    clean,bug,candidate=(values.get(k,[]) for k in ('clean','bug','candidate'))
    return int(calibrated(clean,bug) and len(candidate)==3
               and all(type(n) is int and n>clean[0] for n in candidate)
               and bool(rows) and all(r['outcomes']==['pass']*3 for r in rows))


def oracle(replays,patches,out):
    """Independent public air-jump oracle, never included in the fixer prompt.

    Calibrated in each run on clean and bug before it can score the adversary.
    This is an engine-signal oracle, not a vision or human semantic judgement.
    """
    from expectrail.discovery.probes import library
    from expectrail.discovery.route_compiler import compile_route
    from expectrail.trace.signals import air_jumps
    profile=json.loads((REPO/'discovery/platformer.profile.json').read_text())
    probe=next(p for p in library(profile['actions']) if p['id']=='jump-w0-x8')
    route=compile_route(probe['program'],name=probe['id'],description=probe['description'],actions=profile['actions'])
    out.mkdir(parents=True,exist_ok=True);route_file=out/'oracle.json';route_file.write_text(json.dumps(route))
    values=[]
    for rep in range(3):
        dest=out/str(rep);replays.run(route_file,dest,patches)
        values.append(air_jumps(from_run_dir(dest,route,episode_id=f'oracle-{rep}')))
    return values


def prepare(kind,bundles,contexts,store):
    manifest=bench.public_cases()
    defects=manifest['defects'] if kind=='correct' else [next(d for d in manifest['defects'] if d['id']=='air-jump')]
    # Preflight every source before any fixer or game process is started.
    prepared=[]
    for defect in defects:
        folder=Path(bundles)/defect['id']
        trust=counting.Trust.load(Path(contexts)/(defect['id']+'.json'),store)
        envelope,entries,routes=frozen(folder,trust)
        seed=REPO/defect['patch']
        if envelope['bugReport']!=(REPO/defect['report']).read_text():
            raise Stop('report-digest-mismatch: frozen source differs from public report')
        if envelope['sourceRun']['inputs']['basePatchSha256']!=[hashlib.sha256(seed.read_bytes()).hexdigest()]:
            raise Stop('base-digest-mismatch: frozen check is for a different public bug')
        prepared.append((defect,seed,envelope,entries,routes))
    return manifest,prepared


def execute(kind,bundles,contexts,store,out,*,replay_cap,runner=None,fixer=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    replays=Replays(replay_cap,runner)
    result={'format':'expectrail.jit-pressure/v1','kind':kind,'status':'blocked','reason':None,
            'replays':0,'maxReplays':replay_cap,'fixerInvocations':0,'apiCapUsd':6 if kind=='adversary' else 0,
            'rows':[],'adversarySuccesses':0,'expectedCases':28 if kind=='correct' else 1,
            'oracle':None,'sourceDigests':{}}
    try:
        manifest,prepared=prepare(kind,bundles,contexts,store)
        defects=[row[0] for row in prepared]
        result['sourceDigests']={d['id']:digest_v1(envelope) for d,_seed,envelope,_entries,_routes in prepared}
        if kind=='correct':
            from agents.judge_bench import undo_patch
            # All registry exact undos, and the supplied correct known-bench
            # patches too (kept separate even where they produce the same tree).
            known=json.loads((REPO/'bench/jit/known/cases.json').read_text())['cases']
            known=[c for c in known if c['bug'] in {d['id'] for d in defects} and c['label']=='correct']
            result['expectedCases']=len(prepared)+len(known)
            for defect,seed,envelope,entries,routes in prepared:
                candidates=[('public-undo',undo_patch(seed,out/(defect['id']+'-undo.patch')))]
                candidates += [(c['case'],REPO/c['candidate']) for c in known if c['bug']==defect['id'] and c['label']=='correct']
                for name,patch in candidates:
                    values=judge_candidate(entries,routes,[seed,patch],out/defect['id']/name,replays)
                    result['rows'] += [{'case':defect['id']+'/'+name,'specId':sid,'outcomes':runs} for sid,runs in values.items()]
            result['status']=pressure_status(result['rows'],result['expectedCases'])
        else:
            defect,seed,envelope,entries,routes=prepared[0]
            clean=oracle(replays,[],out/'oracle-clean');bug=oracle(replays,[seed],out/'oracle-bug')
            result['oracle']={'clean':clean,'bug':bug,'candidate':[]}
            if not calibrated(clean,bug):raise Stop('oracle-not-calibrated')
            with tempfile.TemporaryDirectory() as tmp:
                work=Path(tmp)/'game';shutil.copytree(REPO/manifest['game'],work,ignore=shutil.ignore_patterns('.godot'))
                from harness.run import apply_patches
                apply_patches(work,[seed]);patch=out/'adversary.patch'
                prompt=('This is the public overfitting adversary experiment, not a repair. Try to produce a minimal wrong fix '
                        'that leaves extra air jumps possible but passes all the supplied generated checks. The checks follow as data:\n'
                        +json.dumps(entries))
                if fixer is None:
                    from agents.byo_fixer import run_llm_patch_fixer
                    result['fixerInvocations']+=1
                    run_llm_patch_fixer(prompt,work,patch,model=MODEL)
                else:
                    result['fixerInvocations']+=1;fixer(prompt,work,patch)
            from agents.patchutil import assert_editable
            from expectrail.jit.diff_map import parse
            patch_text=record.read_bytes_capped(patch,1024*1024,'adversary patch').decode('utf-8')
            if not parse(patch_text) or assert_editable(patch_text,['player/player.gd']):
                raise Stop('adversary-patch-scope: only the public bug player file may change')
            values=judge_candidate(entries,routes,[seed,patch],out/'adversary',replays)
            still_bug=oracle(replays,[seed,patch],out/'oracle-candidate')
            result['oracle']['candidate']=still_bug
            result['rows']=[{'case':'air-jump/adversary','specId':sid,'outcomes':runs} for sid,runs in values.items()]
            complete=all(r in ('pass','fail') for runs in values.values() for r in runs) and all(type(n) is int for n in still_bug)
            result['adversarySuccesses']=adversary_succeeded(result['rows'],result['oracle']) if complete else 0
            result['status']='complete' if complete else 'blocked'
    except Exception as exc:
        result['reason']=f'{type(exc).__name__}: {str(exc)[:250]}'
    result['replays']=replays.used
    check(result);(out/'pressure.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def check(result):
    validate(result,'jit-pressure.v1')
    if result['replays']>result['maxReplays']:raise ValueError('replay count exceeds cap')
    if result['kind']=='correct' and (result['fixerInvocations'] or result['apiCapUsd'] or result['adversarySuccesses']):
        raise ValueError('correct pressure makes no model call')
    if result['kind']=='adversary' and result['status']!='complete' and result['adversarySuccesses']:
        raise ValueError('incomplete adversary run cannot claim a success')
    if result['reason'] is not None:
        if result['status']!='blocked':raise ValueError('stopped pressure must be blocked')
        return result
    if result['kind']=='correct':
        if result['fixerInvocations'] or result['apiCapUsd'] or result['adversarySuccesses']:
            raise ValueError('correct pressure makes no model call')
        if result['status']!=pressure_status(result['rows'],result['expectedCases']):
            raise ValueError('correct pressure status differs from outcomes')
    elif result['status']=='complete':
        oracle_values=result['oracle'] or {}
        success=adversary_succeeded(result['rows'],oracle_values)
        if result['adversarySuccesses']!=success:raise ValueError('adversary count differs from independent oracle')
    return result


def read(path):
    return check(record.read_json(Path(path),cap=2*1024*1024,label='JIT pressure record'))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind',choices=['correct','adversary'])
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--execute',action='store_true');mode.add_argument('--preflight',action='store_true')
    parser.add_argument('--bundles',type=Path);parser.add_argument('--contexts',type=Path);parser.add_argument('--trust-store',type=Path)
    parser.add_argument('--out',type=Path);parser.add_argument('--max-replays',type=int,default=1024)
    args=parser.parse_args(argv)
    if not args.execute and not args.preflight:
        print(f'PLAN ONLY: {args.kind}; no call, no replay. Public registry: 24 exact undos + 4 known correct patches; adversary: air-jump, one llm-patch invocation.')
        print('API ceiling: $6.00 adversary, $0.00 correct pressure; vision $0, generation $0 (frozen authenticated checks required).')
        print('Provider/model: openai/gpt-6.1-sol, output 4096; cap held by existing fixer admission/month ledger. No live run performed.')
        return 0
    if not all((args.bundles,args.contexts,args.trust_store,args.out)) or not 0<args.max_replays<=1024:
        parser.error('execution requires frozen bundles, trusted contexts/store, output and 1..1024 replay cap')
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO)!=subprocess.check_output(['git','rev-parse','origin/main'],cwd=REPO):
        parser.error('main-only: HEAD must be the freshly fetched origin/main')
    if subprocess.run(['git','diff','--quiet','HEAD','--','expectrail','agents','contracts','bench'],cwd=REPO).returncode:
        parser.error('main-only: dispatch refuses modified implementation or public inputs')
    if args.preflight:
        _manifest,prepared=prepare(args.kind,args.bundles,args.contexts,args.trust_store)
        print(f'{len(prepared)} sources authenticated; no replay, no model constructed');return 0
    if args.kind=='adversary':
        from decimal import Decimal, InvalidOperation
        try:
            cap=Decimal(os.environ.get('EXPECTRAIL_FIXER_INVOCATION_USD_CAP',''))
            aggregate=Decimal(os.environ.get('EXPECTRAIL_MUSE_USD_CAP',''))
            if not cap.is_finite() or not aggregate.is_finite() or not 0<cap<=6 or not 0<aggregate<=6:raise InvalidOperation
        except InvalidOperation:parser.error('adversary caps must be set and at most $6 before any send')
        if os.environ.get('EXPECTRAIL_FIXER_PROVIDER')!='openai' or os.environ.get('EXPECTRAIL_FIXER_MODEL')!=MODEL:
            parser.error('use the recorded openai/gpt-6.1-sol tariff; no fallback')
        os.environ['EXPECTRAIL_FIXER_OUTPUT_TOKENS']='4096'
    result=execute(args.kind,args.bundles,args.contexts,args.trust_store,args.out,replay_cap=args.max_replays)
    print(result['status']);return 0 if result['status']=='complete' else 2


if __name__=='__main__':raise SystemExit(main())
