"""Regenerate small read-only reviews from pinned public game inputs; never approve anything.

Dodge uses the local pinned engine/Xvfb; Breakout reads frozen public PR #570 captures.
Raw captures stay in --artifacts;
only two self-contained HTML summaries go in --out. No model client is constructed.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
from pathlib import Path
from unittest.mock import patch

from expectrail import onboard_page, onboard_review as review
from harness.run import run

REPO=Path(__file__).resolve().parents[1]


def build(name, source, artifacts, output, godot, reuse=False):
    if name!='dodge':raise ValueError('Breakout uses the recorded PR #570 reader below.')
    target=artifacts/name
    if not reuse:
        if target.exists():raise ValueError('Use a new artifacts folder.')
        game=target/'project';shutil.copytree(source,game,ignore=shutil.ignore_patterns('.git','.godot'))
        config={'format':'expectrail.project/v1','adapter':'godot','draft':True,'entryScene':'res://main.tscn',
                'viewport':[480,720],'physicsTicksPerSecond':60,'captureFps':60,
                'inputActions':['move_down','move_left','move_right','move_up','start_game'],
                'bindings':{'player':{'node':'Player','texture':'res://art/playerGrey_walk1.png'}},'routes':['routes/dodge.json'],
                'approvedContracts':['checks/dodge-play-area.json']}
        dest=game/'checks/dodge-play-area.json';dest.parent.mkdir();shutil.copyfile(REPO/'tests/outside/specs/dodge-play-area.json',dest)
        route=REPO/'tests/outside/dodge-the-creeps/routes/dodge.json'
        (game/'expectrail.project.json').write_bytes(review.encoded(config))
        route_dest=game/config['routes'][0];route_dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(route,route_dest)
        changes=REPO/'tests/outside/dodge-the-creeps/changes'
    else:
        game=target/'project'
        config=json.loads((game/'expectrail.project.json').read_bytes())
        route_dest=game/config['routes'][0]
        changes=REPO/'tests/outside/dodge-the-creeps/changes'
    captures={}
    for arm in ('clean','broken','harmless'):
        folder=target/arm
        # Per-process local import cache, never a process-wide shell setting.
        if not reuse:
          with patch.dict(os.environ,{'EXPECTRAIL_GODOT_CACHE':str(target/'import-cache')}):
              run(route_dest,folder,game=game,project=config,godot=godot,
                  patch=None if arm=='clean' else changes/(arm+'.patch'),sandbox='off')
        captures[arm]=folder
    state=target/'review'
    if reuse and state.exists():shutil.rmtree(state)
    state.mkdir()
    record,details=review.prepare(game,state,evidence=captures['clean'],
        broken=[(arm,captures[arm]) for arm in ('broken','harmless')])
    details['project']='Dodge the Creeps'
    manifest=state/'review.json';manifest.write_bytes(review.encoded(record))
    page=onboard_page.render(record,details,state,'local-review-required',review.sha(manifest.read_bytes()),example=True)
    if len(page.encode())>review.MAX_PAGE_BYTES:raise ValueError('Example exceeds page size bound.')
    output.mkdir(parents=True,exist_ok=True);(output/(name+'.html')).write_text(page)
    summary={'project':name,'bytes':len(page.encode()),'engine':json.loads((captures['clean']/'replay.json').read_bytes())['engine'],
             'objects':record['objects'],'checks':details['checks'],'timing':record['timing'],
             'modelCalls':0,'approvedByThisRun':0,'source':'public trial input; engine diagnostic only; not vision evidence'}
    (target/'summary.json').write_bytes(review.encoded(summary))
    print(name,summary['bytes'],summary['objects'],flush=True)


# PR #570 is stacked on the pointer/menu work, which is absent from this base.
# Render its recorded public trial without importing or backporting that harness.
PR570 = 'e14e0c4a27b2fb5798405723b64312b15833d91d'


def recorded_breakout(source, artifacts, output, commit=PR570):
    import re
    import subprocess
    import time
    from expectrail import approval
    from expectrail.contracts import strict_loads, validate, validate_v1
    from expectrail.evaluator import evaluate
    if not re.fullmatch(r'[0-9a-f]{40}',commit):raise ValueError('Use a full public trial commit.')
    def frozen(name):
        try:return subprocess.check_output(['git','show',commit+':'+name],cwd=REPO,stderr=subprocess.PIPE)
        except subprocess.CalledProcessError:raise ValueError('Fetch the public PR #570 commit first: '+commit) from None
    started=review.now();t0=time.monotonic();target=artifacts/'breakout-pr570';target.mkdir(parents=True,exist_ok=True)
    game=target/'project'
    if not game.exists():shutil.copytree(source,game,ignore=shutil.ignore_patterns('.git','.godot'))
    prefix='tests/outside/breakout-pointer/'
    config_raw=frozen(prefix+'expectrail.project.json');config=strict_loads(config_raw.decode())
    (game/'expectrail.project.json').write_bytes(config_raw)
    route_raw=frozen(prefix+config['routes'][0]);route=strict_loads(route_raw.decode())
    route_path=game/config['routes'][0];route_path.parent.mkdir(exist_ok=True);route_path.write_bytes(route_raw)
    specs=[]
    for name in config['approvedContracts']:
        raw=frozen(prefix+name);body=strict_loads(raw.decode());validate(body,'test-spec')
        if 'approval' in body or approval.lint(body):raise ValueError('Trial checks must remain lint-clean drafts.')
        path=game/name;path.parent.mkdir(exist_ok=True);path.write_bytes(raw);specs.append((name,body,raw))
    captures={}
    for label,original in [('clean','pinned-1'),('broken','broken'),('harmless','harmless')]:
        folder=target/label;(folder/'frames').mkdir(parents=True,exist_ok=True)
        original='docs/outside-trials/breakout-pointer/trial-evidence/'+original+'/'
        replay_raw=frozen(original+'replay.json');trace_raw=frozen(original+'trace.json')
        replay=strict_loads(replay_raw.decode())
        if replay['route']['sha256']!=review.sha(route_raw) or replay['trace']['sha256']!=review.sha(trace_raw):
            raise ValueError('The recorded trial does not match its route/trace bytes.')
        (folder/'replay.json').write_bytes(replay_raw);(folder/'trace.json').write_bytes(trace_raw)
        for frame in (20,40,70,100):
            png=frozen(original+f'frame-{frame}.png')
            if review.sha(png)!=replay['frameSha256'][frame]:raise ValueError('The recorded PNG differs from its replay.')
            (folder/'frames'/f'f{frame:08d}.png').write_bytes(png)
        captures[label]=review.capture_data(folder)
    state=target/'review'
    if state.exists():shutil.rmtree(state)
    state.mkdir();objects=[]
    for role,binding in config['bindings'].items():
        cap=captures['clean'];available={f['frame']:f['objects'][role][0]['box'] for f in cap['observations']['frames']
             if f['objects'].get(role) and (cap['folder']/'frames'/f'f{f["frame"]:08d}.png').is_file()}
        samples=[]
        # The first three supplied snapshots are 20, 40 and 70: active play,
        # spanning both movement obligations, before the later game-over overlay.
        for frame in sorted(available)[:3]:
            path=cap['folder']/'frames'/f'f{frame:08d}.png';native=review.png_size(path.read_bytes())
            data,size=review.thumbnail(path);asset=review.asset(state,data,size,frame)
            asset.update(engineBox=[v*size[i%2]/native[i%2] for i,v in enumerate(available[frame])],observerBox=None,score=None)
            samples.append(asset)
        data,size=review.thumbnail(game/binding['texture'].removeprefix('res://'),side=96)
        sprite=review.asset(state,data,size,0)
        objects.append({'role':role,'prompt':next(body['objects'][role]['prompt'] for _,body,_ in specs if role in body['objects']),
                        'selector':binding['node'],'sprite':sprite,'samples':samples,'reviewable':len(samples)==3})
    checks=[]
    for name,body,raw in specs:
        row={'id':body['id'],'approved':False,**review.check_words(body),'results':[]}
        for label,cap in captures.items():
            result=evaluate(body,cap['observations'],route=route['name'],trace=cap['trace'],capture_fps=cap['fps'])
            frame=result.get('firstFrame');image=None
            if frame is not None:
                path=cap['folder']/'frames'/f'f{frame:08d}.png'
                if path.exists():image=review.asset(state,*review.thumbnail(path),frame)
            row['results'].append({'copy':label,'result':result['result'],'reason':result['reason'],'firstFrame':frame,
                                   'image':image,'source':'recorded PR #570 engine diagnostic; not vision evidence'})
        checks.append(row)
    timing={'format':'expectrail.onboard-timing/v1','startedAt':started,'readyAt':review.now(),'machineSeconds':time.monotonic()-t0,
            'humanSeconds':None,'approvedAt':None,'person':None,'state':'review-ready','stages':[
              {'name':'Read recorded public PR #570 trial','status':'completed','seconds':time.monotonic()-t0,
               'reason':commit+'; exact route, trace and PNG hashes verified; no current replay claimed.'},
              *[{'name':name,'status':'skipped','seconds':0,'reason':'No observer evidence supplied; no tuning/proof claimed.'}
                for name in ('observer tuning','observer proof')]]}
    record={'format':'expectrail.onboard-review/v1','project':str(game),'configPath':'expectrail.project.json',
            'configFileSha256':review.sha(config_raw),'config':config,'route':{'path':config['routes'][0],
            'sha256':review.sha(route_raw),'document':route,'existed':True},'inputs':[],
            'objects':[{'role':o['role'],'reviewable':o['reviewable']} for o in objects],
            'specs':[{'path':name,'id':body['id'],'specSha256':approval.spec_sha256(body),'fileSha256':review.sha(raw),
                      'objects':list(body['objects']),'approved':False} for name,body,raw in specs],'timing':timing}
    validate_v1(record,'onboard-review')
    details={'project':'Breakout · PR #570 drafts','objects':objects,'checks':checks,'timing':timing,
             'observer':'No observer answers supplied; recorded PR #570 engine boxes only'}
    page=onboard_page.render(record,details,state,'local-review-required',review.sha(review.encoded(record)),example=True)
    if len(page.encode())>review.MAX_PAGE_BYTES:raise ValueError('Example exceeds page bound.')
    output.mkdir(parents=True,exist_ok=True);(output/'breakout.html').write_text(page)
    summary={'sourceCommit':commit,'routeSha256':review.sha(route_raw),'bytes':len(page.encode()),'checks':checks,
             'objects':record['objects'],'modelCalls':0,'approvedByThisRun':0,'source':'recorded public PR #570 engine trial; not vision evidence'}
    (target/'summary.json').write_bytes(review.encoded(summary))
    print('breakout PR #570',summary['bytes'],[(c['id'],[(r['copy'],r['result'],r['firstFrame']) for r in c['results']]) for c in checks],flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('breakout','dodge','artifacts','out','godot'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--breakout-trial-commit',default=PR570,help='full local Git commit of the recorded public PR #570 trial')
    p.add_argument('--reuse-captures',action='store_true',help='render summaries again from existing artifacts; no replay')
    a=p.parse_args();a.artifacts.mkdir(parents=True,exist_ok=True)
    recorded_breakout(a.breakout.resolve(),a.artifacts.resolve(),a.out.resolve(),a.breakout_trial_commit)
    build('dodge',a.dodge.resolve(),a.artifacts.resolve(),a.out.resolve(),a.godot.resolve(),reuse=a.reuse_captures)


if __name__=='__main__':main()
