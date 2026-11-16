"""No-spend diagnostic rehearsal of #531 on public air-jump; never a clearance.

    EXPECTRAIL_GODOT=/path/to/godot python3 tools/playtest_ingest_rehearsal.py --out /tmp/ingest-proof

Uses the installed engine with the gate's supported engine-only diagnostic rule.
The public CLI, job store, shared judge/evaluator and normal gate are real. Only
worker launching is replaced by in-process runner.work to select that rule.
No model, fixer, approval or reference trace is manufactured. An off-anchor
report and a clean false report use the same real replay as the known-bug report.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from expectrail import cli, resources
from expectrail.gate import verify
from expectrail.orchestrator import engines, playtest, runner, store
from harness import run, tree


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    root=resources.ROOT
    binary=run.find_godot()
    (out/'engine-version.txt').write_text(subprocess.check_output([str(binary),'--version'],text=True))
    clean=out/'clean';bug=out/'air-jump'
    tree.copy(root/'game/platformer',clean,skip=tree.GODOT_SKIP)
    # This is a disposable copy; the bundled game is never modified.
    config={'format':'expectrail.project/v1','adapter':'godot','entryScene':'res://game_singleplayer.tscn',
        'viewport':[800,480],'physicsTicksPerSecond':120,'captureFps':60,
        'inputActions':['move_left','move_right','jump','shoot'],
        'bindings':{'player':{'node':'Level/Player','texture':'res://player/robot.webp'}},
        'routes':['routes/wait.json'],'approvedContracts':['checks/ground.json']}
    (clean/'expectrail.project.json').write_text(json.dumps(config,indent=2)+'\n')
    (clean/'checks').mkdir();(clean/'routes').mkdir()
    shutil.copyfile(root/'agents/specs/player-stays-above-ground.json',clean/'checks/ground.json')
    wait={'format':'expectrail.route/v0','name':'wait','ticks':240,'events':[]}
    (clean/'routes/wait.json').write_text(json.dumps(wait)+'\n')
    shutil.copytree(clean,bug)
    subprocess.run(['patch','-p1','--batch','--forward','-d',str(bug),'-i',str(root/'bugs/reported/air-jump.patch')],check=True)
    for project in (clean,bug):
        subprocess.run(['git','init','-q',str(project)],check=True)
        subprocess.run(['git','-C',str(project),'add','.'],check=True)
        subprocess.run(['git','-C',str(project),'-c','user.name=Expectrail','-c','user.email=local@example.invalid',
                        'commit','-qm','Disposable public rehearsal base'],check=True)
    # Handwritten inputs attempt a third airborne jump. The existing ground check
    # does not assert a jump limit; this run must show that limitation honestly.
    route={'format':'expectrail.route/v0','name':'air-jump-report','ticks':240,'events':[
        {'tick':10,'action':'jump','pressed':True},{'tick':11,'action':'jump','pressed':False},
        {'tick':30,'action':'jump','pressed':True},{'tick':31,'action':'jump','pressed':False},
        {'tick':50,'action':'jump','pressed':True},{'tick':51,'action':'jump','pressed':False}]}
    # Obtain the initial world position from an independent real replay, never guess it.
    path=out/'calibration-route.json';path.write_text(json.dumps(route))
    baseline=verify.harness_replay(path,bug,out/'calibration',True,sandbox='off',checkouts=(bug,),adapter='godot')
    point=next(row['player'] for row in baseline['trace']['rows'] if row['tick']==0)
    report={'format':'expectrail.playtest-report/v1','id':'handwritten-air-jump','producer':{'name':'handwritten','version':'1'},
        'target':{'commit':subprocess.check_output(['git','-C',str(bug),'rev-parse','HEAD'],text=True).strip()},
        'route':route,'bug':(root/'bench/jit/known/air-jump/report.txt').read_text().strip(),
        'fault':{'preFaultTick':0,'faultTick':50,'anchor':{'object':'player','x':point[0],'y':point[1],'tolerancePx':2}}}
    cases=[('known-air-jump',bug,report)]
    off=copy.deepcopy(report);off['id']='off-anchor-report';off['fault']['anchor']['x']+=1000
    cases.append(('anchor-desync',bug,off))
    false=copy.deepcopy(report);false['id']='false-jump-report';false['route']=wait
    false['bug']='The player falls through the floor while standing still.'
    false['target']['commit']=subprocess.check_output(['git','-C',str(clean),'rev-parse','HEAD'],text=True).strip()
    cases.append(('not-reproduced',clean,false))
    jobs=store.JobStore(out/'jobs')
    replay=lambda route,game,folder,frames:verify.harness_replay(route,game,folder,frames,sandbox='off',checkouts=(game,),adapter='godot')
    engine=engines.GodotGate(replay=replay,rule='engine-only',visual=None)
    results=[]
    def spawn(jobs,job):
        runner.work(jobs,job,engines={'godot':engine})
    for name,project,doc in cases:
        path=out/(name+'.json');playtest.write(path,doc)
        log=io.StringIO()
        with mock.patch.object(runner,'spawn',side_effect=spawn),contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
            code=cli.main(['ingest',str(path),'--project',str(project),'--jobs-root',str(jobs.root),'--json'])
        (out/(name+'.log')).write_text(log.getvalue())
        statuses=list((jobs.root/'jobs').glob('*/status.json'))
        status=max(statuses,key=lambda p:p.stat().st_mtime_ns)
        results.append({'case':name,'exit':code,'status':json.loads(status.read_text())})
    (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps([{'case':r['case'],'exit':r['exit'],'decision':r['status']['decision'],'reasons':r['status']['reasons']} for r in results],indent=2))


if __name__=='__main__':main()
