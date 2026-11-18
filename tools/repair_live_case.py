"""One deliberate literal CLI repair of the public fall-through bug. Plan by default.

Pricing, caps, availability and month-state policy come from the existing kit.
All reproduction, retry, sandbox and verdict logic stays in the existing CLI.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

from expectrail import contracts
from expectrail.orchestrator import sample
from tools import live_repair_kit as kit


def parser():
    p=kit.parser();p.description=__doc__
    p.add_argument('--mode',choices=('manual','auto'),default='auto')
    return p


def commands(folder,args,parent=None):
    folder=Path(folder)
    common=['--jobs-root',str(folder/'jobs')]
    if parent:
        return [sys.executable,'-m','expectrail.cli','repair',parent,*common,
                '--agent','llm-patch','--attempts','1']
    argv=[sys.executable,'-m','expectrail.cli','verify','--head',str(folder/'after'),
          '--base',str(folder/'before'),'--game',sample.GAME,'--routes',sample.ROUTE,
          '--specs',sample.SPECS,'--execution-class','isolated',*common,'--json']
    if args.mode=='auto':argv+=['--auto-fix','--auto-fix-agent','llm-patch','--auto-fix-attempts','1',
                                '--auto-fix-usd-cap',str(args.fixer_total)]
    return argv


def execute(argv,env,folder,name):
    (folder/(name+'.command.json')).write_text(json.dumps(argv,indent=2)+'\n')
    with (folder/(name+'.stdout')).open('w') as stdout,(folder/(name+'.stderr')).open('w') as stderr:
        proc=subprocess.run(argv,env=env,stdout=stdout,stderr=stderr)
    return proc.returncode,(folder/(name+'.stdout')).read_text()


def main(argv=None):
    args=parser().parse_args(argv)
    if args.attempts!=1:raise ValueError('this one-case run sheet permits one attempt only')
    quote=kit.plan(args)|{'scope':'one public fall-through comparison using the literal CLI','mode':args.mode}
    print(json.dumps(quote,indent=2))
    if not args.run:return 0
    env=kit.environment(args)
    if not env.get('EXPECTRAIL_FIXER_API_KEY') or not env.get('MODEL_API_KEY'):
        raise ValueError('both dedicated provider keys are required before this deliberate run')
    folder=args.out.resolve();folder.mkdir(parents=True,exist_ok=False)
    sample.checkout(folder/'before',bug=False);sample.checkout(folder/'after',bug=True)
    # The same full public wait route used by the engine fixture tests; checks
    # retain their exact approved bytes. Nothing is approved or weakened.
    route=json.loads((kit.ROOT/'contracts/examples/playtest-report-fall-through.json').read_text())['route']
    route['name']='smoke'
    for side in ('before','after'):(folder/side/sample.ROUTE).write_text(json.dumps(route))
    (folder/'plan.json').write_text(json.dumps(quote,indent=2)+'\n')
    code,text=execute(commands(folder,args),env,folder,'verify')
    parent=json.loads(text)
    if code!=1 or parent.get('decision')!='reject':
        print('Original verification did not reject; no standalone repair was started.');return 2
    if args.mode=='manual':execute(commands(folder,args,parent['id']),env,folder,'repair')
    paths=list((folder/'jobs/jobs'/parent['id']).glob('repair-*/repair-run.json'))
    if len(paths)!=1:raise ValueError('expected one existing repair-run record')
    doc=contracts.load_strict(paths[0],'repair-run')
    print(json.dumps(doc,indent=2))
    return 0 if doc['result']['decision']=='accept' else 2


if __name__=='__main__':raise SystemExit(main())
