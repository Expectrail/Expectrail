"""Manual, public-only #271 pressure runs. Default is a plan; never auto-dispatch.

Frozen, authenticated counting checks are prerequisites, not generated here.
Correct pressure covers every exact undo in the 24-defect public registry, plus
all registered correct known-bench patches. The adversary is one attempt on the
public air-jump bug; only that test intentionally gives its fixer the checks.

Counting pixel checks (#286) are replayed by correct pressure only, and only
those judged by the no-model ``visual-sensor``: each candidate is replayed with
frames and judged with a template bank whose digest must be the one the frozen
check was judged with. A pixel check for any other observer, or with no bank
given, stops the dispatch (``pixel-checks-not-replayed``), as does any counting
pixel check under the adversary: never replay fewer checks than count.
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
    def run(self, route, out, patches, *, frames=False):
        if self.used>=self.cap:raise Stop('replay-cap: nothing further replayed')
        self.used+=1
        if self.runner is None:
            from harness.run import run
            return run(route,out,patches=patches,capture_frames=frames,sandbox='require')
        # Trace replays call a stand-in runner as before; a pixel replay asks it for frames.
        return self.runner(route,out,patches=patches,sandbox='require',**({'capture_frames':True} if frames else {}))


def frozen(folder, trust, observer=None):
    """(envelope, trace entries, routes, pixel checks) of one frozen, authenticated bundle.

    ``observer`` judges the counting pixel checks: without one, or when a check names another observer or
    was judged under another setting (another bank), the dispatch stops before any replay."""
    if bench.private_name(folder):raise Stop('public-only: held-out/fresh names refused')
    envelope=record.read_json(folder/'generated-counting.json',cap=8*1024*1024)
    proof=counting.read(envelope,trust=trust)
    rows=[r for r in proof.block['rows'] if record.counting_row(r)]
    if not rows:raise Stop('no-counting-checks: no fixer or model may start')
    counted={r['specId'] for r in rows if r.get('kind')!='pixel'}
    run=envelope['sourceRun'];entries=[p for p in run['proposed'] if p['spec']['id'] in counted]
    digests={p['id']:p['routeSha256'] for p in run['probes']};routes={}
    pixels=pixel_checks(run,[r for r in rows if r.get('kind')=='pixel'],observer,digests)
    for pid in sorted({pid for p in entries for pid in p['probeIds']}|{p['check']['probe'] for p in pixels}):
        path=folder/'jit-routes'/('jit-'+pid.removeprefix('jit-')+'.json')
        if not path.resolve().is_relative_to(folder.resolve()):raise Stop('route path escapes frozen bundle')
        route=record.read_json(path,cap=1024*1024);validate(route,'route')
        if digest_v1(route)!=digests[pid]:raise Stop('route-digest-mismatch')
        routes[pid]=route
    return envelope,entries,routes,pixels


def pixel_checks(run, rows, observer, digests):
    """The counting pixel rows' checks, each with the setting it was judged under, or Stop.

    The rows come from an envelope ``counting.read`` has recomputed and authenticated, so the check, its
    observer and its setting are those of the signed source run."""
    if not rows:return []
    if observer is None:
        # Never replay fewer frozen checks than count (#271, #286).
        raise Stop('pixel-checks-not-replayed: a counting pixel check needs an observer this dispatch was not given')
    name,setting=getattr(observer,'name',None),observer.setting()
    source={p['check']['id']:p for p in run.get('pixelChecks') or []}
    out=[]
    for row in rows:
        if row['observer']!=name:
            raise Stop(f"pixel-checks-not-replayed: {row['specId'][:80]} is judged by {row['observer'][:40]}, "
                       f"and only {str(name)[:40]} is replayed here")
        if row['setting']!=setting:
            raise Stop(f"pixel-setting-mismatch: {row['specId'][:80]} was judged under another setting "
                       "(another sensor bank) than this dispatch's")
        src=source.get(row['specId'])
        if src is None or src['setting']!=row['setting'] or src['check']['observer']!=row['observer']:
            raise Stop('pixel-check-mismatch: the row has no matching check in the source run')
        pid=src['check']['probe']
        if row['probeIds']!=[pid] or row['routeSha256']!=[digests.get(pid)]:
            raise Stop('route-digest-mismatch: the pixel check names another route than the source run')
        out.append({'check':src['check'],'setting':row['setting']})
    return out


PIXEL_OUTCOMES={'pass':'pass','fail':'fail'}


def judge_pixel(pixels,routes,patches,out,replays,observer):
    """{checkId: [outcome per run]} for the counting pixel checks on one candidate: each probe replayed with
    frames three times, the observer asked about its planned frames inside the checks' windows (as the
    run that judged them was), and each check judged by ``pixel.judge``.

    A run that cannot be decided (a gap, an observer that fails or answers under another setting) is
    ``insufficient_observation``: never a pass, so correct pressure is then blocked, not complete."""
    from expectrail.jit import pixel
    from expectrail.jit.run import _pixel_plans
    bindings=pixel.bindings_for();path=Path(out)
    values={p['check']['id']:[] for p in pixels};wanted={p['check']['id']:p['setting'] for p in pixels}
    by_probe={}
    for p in pixels:by_probe.setdefault(p['check']['probe'],[]).append(p['check'])
    kept,plans,refused=_pixel_plans(by_probe,{pid:(routes[pid],None) for pid in by_probe},observer)
    for check,_why in refused:values[check['id']]=['insufficient_observation']*3
    for pid,group in sorted(kept.items()):
        route=routes[pid];windows,_planned=plans[pid]
        objects=sorted({c['object'] for c in group if pixel.named(c['object'],bindings)})
        player=pixel.asks_player(group,bindings)
        route_file=path/(pid.replace('/','-')+'.json');path.mkdir(parents=True,exist_ok=True)
        route_file.write_text(json.dumps(route))
        for rep in range(3):
            destination=path/f'pixel-{rep}'/pid
            replays.run(route_file,destination,patches,frames=True)
            try:
                setting,run,_images=pixel.observe(observer,destination,route,objects,player,windows)
            except pixel.PixelError:
                for c in group:values[c['id']].append('insufficient_observation')
                continue
            for c in group:
                result=pixel.judge(c,run,bindings)['result'] if setting==wanted[c['id']] else 'needs-review'
                values[c['id']].append(PIXEL_OUTCOMES.get(result,'insufficient_observation'))
    return values


def judge_candidate(entries,routes,patches,out,replays):
    path=Path(out);path.mkdir(parents=True,exist_ok=True)
    values={p['spec']['id']:[] for p in entries}
    # Only the probes the trace checks name: a probe only a pixel check needs is replayed with frames.
    needed={pid for p in entries for pid in p['probeIds']}
    if not needed:return values
    for rep in range(3):
        eps={}
        for pid,route in sorted(routes.items()):
            if pid not in needed:continue
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


def prepare(kind,bundles,contexts,store,observer=None):
    manifest=bench.public_cases()
    defects=manifest['defects'] if kind=='correct' else [next(d for d in manifest['defects'] if d['id']=='air-jump')]
    # Preflight every source before any fixer or game process is started.
    prepared=[]
    for defect in defects:
        folder=Path(bundles)/defect['id']
        trust=counting.Trust.load(Path(contexts)/(defect['id']+'.json'),store)
        # The adversary is given the trace checks only, so a counting pixel check stops it (no observer).
        envelope,entries,routes,pixels=frozen(folder,trust,observer if kind=='correct' else None)
        seed=REPO/defect['patch']
        if envelope['bugReport']!=(REPO/defect['report']).read_text():
            raise Stop('report-digest-mismatch: frozen source differs from public report')
        if envelope['sourceRun']['inputs']['basePatchSha256']!=[hashlib.sha256(seed.read_bytes()).hexdigest()]:
            raise Stop('base-digest-mismatch: frozen check is for a different public bug')
        prepared.append((defect,seed,envelope,entries,routes,pixels))
    return manifest,prepared


def execute(kind,bundles,contexts,store,out,*,replay_cap,runner=None,fixer=None,observer=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    replays=Replays(replay_cap,runner)
    result={'format':'expectrail.jit-pressure/v1','kind':kind,'status':'blocked','reason':None,
            'replays':0,'maxReplays':replay_cap,'fixerInvocations':0,'apiCapUsd':6 if kind=='adversary' else 0,
            'rows':[],'adversarySuccesses':0,'expectedCases':28 if kind=='correct' else 1,
            'oracle':None,'sourceDigests':{}}
    if observer is not None:
        if kind!='correct':raise ValueError('only correct pressure replays pixel checks')
        result['pixelObserver']={'name':observer.name,'setting':observer.setting(),**pixel_plan(observer)}
    try:
        manifest,prepared=prepare(kind,bundles,contexts,store,observer)
        defects=[row[0] for row in prepared]
        result['sourceDigests']={d['id']:digest_v1(envelope) for d,_seed,envelope,_entries,_routes,_pixels in prepared}
        if kind=='correct':
            from agents.judge_bench import undo_patch
            # All registry exact undos, and the supplied correct known-bench
            # patches too (kept separate even where they produce the same tree).
            known=json.loads((REPO/'bench/jit/known/cases.json').read_text())['cases']
            known=[c for c in known if c['bug'] in {d['id'] for d in defects} and c['label']=='correct']
            result['expectedCases']=len(prepared)+len(known)
            for defect,seed,envelope,entries,routes,pixels in prepared:
                candidates=[('public-undo',undo_patch(seed,out/(defect['id']+'-undo.patch')))]
                candidates += [(c['case'],REPO/c['candidate']) for c in known if c['bug']==defect['id'] and c['label']=='correct']
                for name,patch in candidates:
                    values=judge_candidate(entries,routes,[seed,patch],out/defect['id']/name,replays)
                    result['rows'] += [{'case':defect['id']+'/'+name,'specId':sid,'outcomes':runs} for sid,runs in values.items()]
                    if pixels:
                        seen=judge_pixel(pixels,routes,[seed,patch],out/defect['id']/name,replays,observer)
                        result['rows'] += [{'case':defect['id']+'/'+name,'specId':sid,'outcomes':runs,'kind':'pixel'}
                                           for sid,runs in seen.items()]
            result['status']=pressure_status(result['rows'],result['expectedCases'])
        else:
            defect,seed,envelope,entries,routes,_pixels=prepared[0]
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


def pixel_plan(observer):
    """The frame plan the pixel checks are replayed with. The source run does not record it, so it is an
    input of the dispatch (``--sensor-every``, ``--sensor-first``) and is written beside the result."""
    return {'every':observer.every,'first':observer.first}


def check(result):
    validate(result,'jit-pressure.v1')
    pixel_rows=[r for r in result['rows'] if r.get('kind')=='pixel']
    if result.get('pixelObserver') is not None and result['kind']!='correct':
        raise ValueError('only correct pressure replays pixel checks')
    if pixel_rows and result.get('pixelObserver') is None:
        raise ValueError('pixel rows need the observer and bank that judged them')
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
    parser.add_argument('--sensor-bank',type=Path,help='correct pressure: the template bank the frozen visual-sensor checks were judged with')
    parser.add_argument('--sensor-every',type=int,default=10);parser.add_argument('--sensor-first',type=int)
    args=parser.parse_args(argv)
    if args.sensor_bank is not None and args.kind!='correct':parser.error('only correct pressure replays pixel checks')
    if not args.execute and not args.preflight:
        print(f'PLAN ONLY: {args.kind}; no call, no replay. Public registry: 24 exact undos + 4 known correct patches; adversary: air-jump, one llm-patch invocation.')
        print('API ceiling: $6.00 adversary, $0.00 correct pressure; vision $0, generation $0 (frozen authenticated checks required).')
        print('Pixel checks: correct pressure replays visual-sensor checks with frames given --sensor-bank (no model, $0); SAM checks and the adversary stop.')
        print('Provider/model: openai/gpt-6.1-sol, output 4096; cap held by existing fixer admission/month ledger. No live run performed.')
        return 0
    if not all((args.bundles,args.contexts,args.trust_store,args.out)) or not 0<args.max_replays<=1024:
        parser.error('execution requires frozen bundles, trusted contexts/store, output and 1..1024 replay cap')
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO)!=subprocess.check_output(['git','rev-parse','origin/main'],cwd=REPO):
        parser.error('main-only: HEAD must be the freshly fetched origin/main')
    if subprocess.run(['git','diff','--quiet','HEAD','--','expectrail','agents','contracts','bench'],cwd=REPO).returncode:
        parser.error('main-only: dispatch refuses modified implementation or public inputs')
    observer=None
    if args.sensor_bank is not None:
        from expectrail.jit.template_observer import TemplateSensorObserver
        try:observer=TemplateSensorObserver(args.sensor_bank,every=args.sensor_every,first=args.sensor_first)
        except ValueError as exc:parser.error(str(exc)[:200])
    if args.preflight:
        _manifest,prepared=prepare(args.kind,args.bundles,args.contexts,args.trust_store,observer)
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
    result=execute(args.kind,args.bundles,args.contexts,args.trust_store,args.out,replay_cap=args.max_replays,observer=observer)
    print(result['status']);return 0 if result['status']=='complete' else 2


if __name__=='__main__':raise SystemExit(main())
