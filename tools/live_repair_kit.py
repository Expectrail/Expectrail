"""One explicitly authorized public fall-through run; default is a spend-free plan.

This prepares public inputs and calls the existing CLI. It contains no generator,
fixer, retry, reproduction or candidate-decision implementation.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from decimal import Decimal, InvalidOperation

from expectrail import resources, spend
from expectrail.orchestrator import playtest

MODEL='gpt-6.1-sol'
ROOT=resources.ROOT


def amount(value):
    try:
        n=Decimal(value)
        if not n.is_finite() or n < 0 or n > 200 or n.as_integer_ratio()[1] > 10**9:
            raise ValueError
        return n
    except (InvalidOperation,ValueError):raise argparse.ArgumentTypeError('cap must be 0..200 USD, at most nine decimal places')


def plan(args):
    if not 1 <= args.attempts <= 3 or not 1 <= args.output_tokens <= 4096:
        raise ValueError('attempts must be 1..3 and output tokens 1..4096')
    if args.fixer_invocation <= 0 or args.fixer_total < args.fixer_invocation or args.vision <= 0:
        raise ValueError('positive invocation/vision caps and an aggregate cap covering an invocation are required')
    if any(getattr(args,role) != 0 for role in ('spec','triage','glimmer')):
        raise ValueError('this kit requires spec, triage and glimmer caps to be zero')
    price=next(p for p in spend.read_provider_capability(ROOT/'contracts/examples/provider-capabilities/openai.json')['tokenPrices'] if p['model']==MODEL)
    from datetime import date
    if not price.get('validUntil') or date.today()>date.fromisoformat(price['validUntil']):
        raise ValueError('fixer-model-unavailable: model/price review expired')
    if price.get('status')!='active':raise ValueError('fixer-model-unavailable: reviewed model is not active')
    return {'scope':'one public fall-through report; no generated checks', 'provider':'openai','model':MODEL,
        'attempts':args.attempts,'invocationUsd':str(args.fixer_invocation),'fixerTotalUsd':str(args.fixer_total),
        'visionPerWorkerUsd':str(args.vision),'outputTokens':args.output_tokens,
        'fixerEnvelopeUsd':str(min(args.fixer_invocation*args.attempts,args.fixer_total)),
        'visionEnvelopeUsd':str(args.vision*(1+args.attempts)),
        'totalEnvelopeUsd':str(min(args.fixer_invocation*args.attempts,args.fixer_total)+args.vision*(1+args.attempts)),
        'prices':price,'paidCallsMadeByPlan':0}


def environment(args):
    env=dict(os.environ)
    # Explicit settings prevent ambient backend/model/tier choices changing the quote.
    env.update(EXPECTRAIL_FIXER_PROVIDER='openai',EXPECTRAIL_FIXER_MODEL=MODEL,
        EXPECTRAIL_FIXER_API_BASE='https://api.openai.com/v1',
        EXPECTRAIL_FIXER_INVOCATION_USD_CAP=str(args.fixer_invocation),
        EXPECTRAIL_MUSE_USD_CAP=str(args.fixer_total),EXPECTRAIL_FIXER_OUTPUT_TOKENS=str(args.output_tokens),
        EXPECTRAIL_VISION_BACKEND='sam',EXPECTRAIL_SAM_MODEL='sam-3.1',
        EXPECTRAIL_MODEL_API_BASE='https://api.meta.ai/v1',EXPECTRAIL_SAM_USD_CAP=str(args.vision),
        EXPECTRAIL_SPEC_USD_CAP='0',EXPECTRAIL_TRIAGE_USD_CAP='0',EXPECTRAIL_GLIMMER_USD_CAP='0',
        EXPECTRAIL_SANDBOX='require',EXPECTRAIL_SAM_CONFIRM='1',EXPECTRAIL_KEYFRAMES_ONLY='0',
        EXPECTRAIL_SAM_CACHE=str(args.out.resolve()/'sam-cache'))
    for name in ('EXPECTRAIL_MODEL_MONTH_LEDGER','EXPECTRAIL_VISION_MONTH_LEDGER'):
        path=Path(env.get(name,'')).expanduser()
        if not env.get(name) or not path.is_absolute() or path.resolve().is_relative_to(ROOT):
            raise ValueError(name+' must name a durable absolute file outside the checkout')
    return env


def prepare(folder):
    from tools.playtest_fall_through import _project
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    report=playtest.load(ROOT/'contracts/examples/playtest-report-fall-through.json')
    project=folder/'project'
    report['target']['commit']=_project(project,bug=True,route=report['route'])
    playtest.write(folder/'report.json',report)
    return project


def command(folder,args):
    return [sys.executable,'-m','expectrail.cli','ingest',str(folder/'report.json'),'--project',str(folder/'project'),
        '--jobs-root',str(folder/'jobs'),'--execution-class','isolated','--repair','--repair-agent','llm-patch',
        '--repair-attempts',str(args.attempts),'--json']


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=Path('runs/one-live-repair'))
    p.add_argument('--run',action='store_true',help='explicitly authorize this one prepared public report; requires keys and durable ledgers')
    p.add_argument('--attempts',type=int,default=1)
    p.add_argument('--output-tokens',type=int,default=4096)
    for flag,default in [('fixer-invocation','6'),('fixer-total','6'),('vision','2'),('spec','0'),('triage','0'),('glimmer','0')]:
        p.add_argument('--'+flag,type=amount,default=amount(default))
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    quote=plan(args)
    if not args.run:
        print(json.dumps(quote,indent=2));return 0
    env=environment(args)
    folder=args.out.resolve();prepare(folder)
    (folder/'plan.json').write_text(json.dumps(quote,indent=2)+'\n')
    with (folder/'command.stdout.json').open('w') as stdout,(folder/'command.stderr.log').open('w') as stderr:
        proc=subprocess.run(command(folder,args),env=env,stdout=stdout,stderr=stderr)
    # Keep the CLI's outcome visible. Never synthesize a successful gate result.
    print((folder/'command.stdout.json').read_text())
    return proc.returncode


if __name__=='__main__':raise SystemExit(main())
