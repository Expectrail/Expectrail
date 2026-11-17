"""Measure one closing-link declaration before/after using the existing public known-bug bench.

No generation, fixer, live observer or new decision rule. Executes only the trusted
baseline intent module named by --before-ref (default: the assigned starting main).
The source reference is operator input, never supplied by the synthetic PR body.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import types

from expectrail.gate import intent, known_bench as bench, record, verify

BEFORE = '5d25639b7e53e5989cf2eb062544727eeefb02e1'


def baseline(ref):
    if not re.fullmatch('[0-9a-f]{40}',ref):raise ValueError('name the full trusted baseline commit')
    source=subprocess.check_output(['git','show',ref+':expectrail/gate/intent.py'],cwd=bench.REPO)
    name='_expectrail_known_bench_before'
    module=types.ModuleType(name);sys.modules[name]=module
    exec(compile(source,'<trusted-baseline-intent>','exec'),vars(module))
    return module


def run(body, work, *, before_ref=BEFORE, run_gate=verify.run_gate):
    before=baseline(before_ref)
    pr={'number':7,'base':{'sha':before_ref},'head':{'sha':'1'*40},'labels':[{'name':'intent:none'}],'body':body}
    selected={'none':before.of_pull_request(pr).intent,'fix':intent.of_pull_request(pr).intent}
    if selected!={'none':'none','fix':'fix'}:
        raise ValueError('the body must expose a none-to-fix closing-link transition before any replay')
    metadata=intent.pull_request_metadata(pr)
    calls=[]
    def gate(**kwargs):
        arm=kwargs['intent'];kwargs['intent']=selected[arm]
        kwargs['pr']=metadata if arm=='fix' else {k:v for k,v in metadata.items() if k!='fixLinks'}
        # The approved position check needs no PNGs. This is a headless diagnostic,
        # explicitly engine-only; it does not measure vision or OS containment.
        def replay(route,game,out,frames):
            return verify.harness_replay(route,game,out,False,sandbox='off',checkouts=(kwargs['repo'],kwargs['base']))
        kwargs.update(replay=replay,rule=record.ENGINE_ONLY)
        doc=run_gate(**kwargs)
        calls.append((arm,doc['decision']))
        return doc
    rows=[]
    for case in bench.load_cases():
        print('Known case: '+case['case'],flush=True)
        rows.append(bench.run_case(case,Path(work)/case['case'],run_gate=gate))
    result=bench.make_record(rows,engine=bench._engine())
    problems=bench.problems(result)
    if problems:raise ValueError('; '.join(problems))
    return result, {'beforeRef':before_ref,'body':body,'labels':pr['labels'],'beforeIntent':selected['none'],
                    'afterIntent':selected['fix'],'fixLinks':metadata['fixLinks'],'gateCalls':len(calls),
                    'capture':'headless, no PNGs','sandbox':'off (diagnostic)','rule':'engine-only','liveModelCalls':0}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before-ref',default=BEFORE)
    p.add_argument('--body',default='Fixes #284')
    p.add_argument('--work',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--markdown',type=Path,required=True)
    p.add_argument('--provenance',type=Path,required=True,help='local command/provenance log, not a gate record')
    args=p.parse_args(argv)
    result,source=run(args.body,args.work,before_ref=args.before_ref)
    args.out.write_text(json.dumps(result,indent=2)+'\n')
    args.provenance.write_text(json.dumps(source,indent=2)+'\n')
    # The existing reader checks the exact standard record written above.
    bench.load(args.out)
    text=('# Closing-link intent on the public known-bug bench (#284)\n\n'
          'Recorded by `python3 -m tools.linked_bug_bench`, wrapping the existing bench runner and renderer below. '
          'The same PR body, `Fixes #284`, with label `intent:none`, is classified by the trusted starting '
          'commit `'+args.before_ref+'` (none) and the patched classifier (fix). '
          'Real headless Godot; sandbox off for this diagnostic; engine-only, no PNGs or model calls. '
          'This does not measure the vision-enabled CI gate or replay containment.\n\n'+bench.render(result))
    args.markdown.write_text(text)
    print(json.dumps(source,indent=2));print(text)
    return 0


if __name__=='__main__':raise SystemExit(main())
