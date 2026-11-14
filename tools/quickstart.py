"""Execute the six published quickstart blocks, then inspect their real saved evidence.

Run explicitly in CI's engine-equipped package job. Unit tests exercise the reader, shell driver
and result checks with offline stand-ins; there is no skip-to-success mode in this command.
"""
from __future__ import annotations
import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess

from tools.front_door import Page, ROOT, problems

EXPECTED = [('install',0),('doctor',3),('sample',3),('project',0),('verify',2),('report',2)]


def commands(path=ROOT/'docs/quickstart.html'):
    steps = Page(Path(path).read_text(encoding='utf-8')).steps
    if [(s['name'],s['exit']) for s in steps] != EXPECTED or any(not s['command'].strip() for s in steps):
        raise ValueError('quickstart must publish the six named blocks and their documented no-credentials exits')
    return steps


def run_steps(steps, cwd, env, log):
    """One Bash shell preserves activation and project/job variables across the exact page blocks."""
    lines = ['set -eu']
    for step in steps:
        # Block text is the reviewed documentation, executed as code in a disposable checkout.
        lines += ['if {',step['command'],'}; then quickstart_code=0; else quickstart_code=$?; fi',
                  f'printf "quickstart {step["name"]}: exit %s (expected {step["exit"]})\\n" "$quickstart_code"',
                  f'test "$quickstart_code" -eq {step["exit"]}']
    with Path(log).open('w',encoding='utf-8') as output:
        done = subprocess.run(['bash','--noprofile','--norc','-c','\n'.join(lines)],cwd=cwd,env=env,
                              stdout=output,stderr=subprocess.STDOUT)
    if done.returncode:
        raise ValueError(f'a published command had an unexpected exit; see {log}')


def copy_checkout(source, target):
    """Copy only install inputs and the public second-project example; never sweep the repository."""
    source,target = Path(source),Path(target)
    def copy(name):
        dest = target/name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/name,dest)
    for name in ('pyproject.toml','setup.py','README.md','LICENSE','NOTICE'):
        copy(name)
    parsed = ast.parse((source/'setup.py').read_text())
    modules = next(ast.literal_eval(n.value) for n in parsed.body if isinstance(n,ast.Assign)
                   and any(isinstance(t,ast.Name) and t.id=='BUNDLED_MODULES' for t in n.targets))
    for package in ('expectrail','expectrail._bundle.harness','expectrail._bundle.agents'):
        folder = package.rsplit('.',1)[-1]
        for module in modules[package]:copy(f'{folder}/{module}.py')
    for folder in ('expectrail/gate','expectrail/orchestrator'):
        for file in (source/folder).glob('*.py'):copy(str(file.relative_to(source)))
    for pattern in ('contracts/*.json','agents/specs/*.json','harness/godot/*.gd','harness/routes/*.json'):
        for file in source.glob(pattern):copy(str(file.relative_to(source)))
    for name in ('harness/get_godot.sh','harness/macos/get_godot_mac.sh','bugs/physics-fall-through/v1.patch'):
        copy(name)
    def ignore(folder,names):
        return [n for n in names if n in ('.git','.godot','__pycache__','Expectrail-heldout') or n.startswith(('fresh-','.env'))]
    for folder in ('game/platformer','tests/projects/crate-run'):
        shutil.copytree(source/folder,target/folder,ignore=ignore)


def validate_results(work):
    """An expected exit alone cannot hide a failed replay, an accept without vision, or draft approval."""
    from expectrail.gate import record
    from expectrail.orchestrator import store
    work=Path(work)
    doctor=json.loads((work/'doctor.json').read_text())
    from expectrail.doctor import problems as doctor_problems
    assert not doctor_problems(doctor), 'invalid doctor document'
    assert {c['id'] for c in doctor['checks']} == {'python','godot','display','opengl','disk','sandbox','patch','curl','unzip','vision-key','vision-cap'}
    missing=sorted((c['id'],c['status']) for c in doctor['checks'] if c['required'] and c['status']!='ok')
    assert missing==[('vision-cap','missing'),('vision-key','missing')], missing
    assert doctor['ok'] is False
    samples=json.loads((work/'sample.json').read_text())
    assert len(samples)==3
    statuses=[case['status'] for case in samples]
    assert [s['decision'] for s in statuses]==['needs-review','reject','needs-review']
    jobs=store.JobStore(work/'runs/quickstart-sample')
    for status in statuses:
        assert status['phase']=='completed' and status['output']=='output', status
        assert status==jobs.status(status['id'])
        findings=record.read_record(jobs.paths(status['id']).output/'findings.json')
        assert findings['decision']==status['decision']
        assert findings['observers']==status['observers']=={'rule':'both','visual':None}
        assert findings['checks'] and findings['isolation']['replays']>0
        for check in findings['checks']:
            assert check['observed']['after']['engine'] in ('pass','fail')
            assert check['observed']['after']['visual']=='not-asked'
        assert (status['decision']=='reject')==any(c['observed']['after']['engine']=='fail' for c in findings['checks'])
        for setting in ('MODEL_API_KEY','EXPECTRAIL_SAM_USD_CAP'):
            assert any(d['code']=='PROVIDER_FAILED' and setting in d['detail'] for d in status['diagnostics'])
    draft=json.loads((work/'verification.json').read_text())
    jobs=store.JobStore(work/'runs/quickstart-project')
    assert draft==jobs.status(draft['id'])
    assert (draft['phase'],draft['decision'])==('completed','needs-review')
    findings=record.read_record(jobs.paths(draft['id']).output/'findings.json')
    assert findings['drafts']==1 and findings['checks']==[] and findings['isolation']['replays']==0
    spec=json.loads((work/'tests/projects/crate-run/specs/crate-stays-above-floor.json').read_text())
    assert 'approval' not in spec
    assert (jobs.paths(draft['id']).root/'viewer/index.html').is_file(), 'report did not publish its evidence page'
    return {'sample':[s['decision'] for s in statuses],'project':draft['decision'],
            'drafts':findings['drafts'],'projectReplays':findings['isolation']['replays']}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--out',type=Path,required=True,help='new output directory; evidence and command log are kept')
    p.add_argument('--godot',type=Path,help='existing binary; otherwise use the repository engine/cache')
    args=p.parse_args(argv)
    found=problems()
    if found:p.exit(1,'\n'.join(found)+'\n')
    steps=commands()
    out=args.out.resolve()
    if out.exists():p.error('--out must be a new directory')
    # Explicitly refuse source-game descendants even before copying.
    for game in (ROOT/'game/platformer',ROOT/'game/unity-platformer'):
        if out==game.resolve() or out.is_relative_to(game.resolve()):p.error('--out cannot be in a source game')
    out.mkdir(parents=True)
    checkout=out/'checkout';copy_checkout(ROOT,checkout)
    env=dict(os.environ)
    for name in ('MODEL_API_KEY','EXPECTRAIL_SAM_USD_CAP','PYTHONPATH','PYTHONHOME'):
        env.pop(name,None)
    env.update(PIP_REQUIRE_VIRTUALENV='true',PIP_DISABLE_PIP_VERSION_CHECK='1',PIP_NO_INPUT='1')
    if args.godot:
        env['EXPECTRAIL_GODOT']=str(args.godot.resolve())
    elif 'EXPECTRAIL_GODOT' not in env:
        from harness.run import find_godot
        env['EXPECTRAIL_GODOT']=str(find_godot())
    try:
        run_steps(steps,checkout,env,out/'commands.log')
        summary=validate_results(checkout)
    except (ValueError,AssertionError,OSError,KeyError) as exc:
        p.exit(1,f'Quickstart FAILED: {exc}\nEvidence retained at {out}\n')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('Quickstart PASS: all six published blocks executed; real sample evidence and unapproved project boundary checked.')
    print(json.dumps(summary));print(f'Evidence retained at {out}')
    return 0


if __name__=='__main__':raise SystemExit(main())
