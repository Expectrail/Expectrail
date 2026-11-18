"""Real engine/CLI fixture driver. Trace-backed vision is NOT independent vision.

Only tests import this. No production environment setting selects this observer.
It uses the existing gate and fixer fixture, never a second decision rule.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from agents.observations import from_trace_synthetic


class TraceSegments:
    model = 'trace-fixture-not-a-model'
    provider = 'offline-fixture-not-vision'

    def segment_in(self, png, boxes):
        png = Path(png)
        trace = json.loads((png.parent.parent / 'trace.json').read_text())
        frames = from_trace_synthetic(trace)['frames']
        objects = frames[int(png.stem[1:])]['objects']['player']
        return objects[:1] if objects else []


class TraceVision:
    def describe(self):
        return {'name': 'trace-fixture', 'provider': TraceSegments.provider, 'model': TraceSegments.model}

    def segmenter(self): return TraceSegments()

    def look(self, spec, run, *, keep=True):
        return from_trace_synthetic(run['trace'], replay_sha256=run['replaySha256'])


def bootstrap():
    from expectrail.orchestrator import engines
    engines.ENGINES = {'godot': engines.GodotGate(visual=TraceVision())}
    def forbidden(*args, **kwargs): raise AssertionError('fixture attempted a model or network transport')
    from expectrail import providers
    from agents import sam_observations
    providers.chat_completion = forbidden
    sam_observations.MetaSamClient = forbidden
    import urllib.request
    urllib.request.urlopen = forbidden
    urllib.request.build_opener = forbidden


def exercise(folder, case, *, isolated):
    from expectrail import contracts
    from expectrail.orchestrator import sample
    from expectrail.gate import record
    root = Path(folder).resolve(); root.mkdir(parents=True)
    before = sample.checkout(root / 'before', bug=False)
    after = sample.checkout(root / 'after', bug=True)
    # Reuse #551's public hand-written fall-through route. The approved check
    # bytes and game source are unchanged; both versions have identical policy.
    route = json.loads((Path(__file__).resolve().parents[1] / 'contracts/examples/playtest-report-fall-through.json').read_text())['route']
    route['name'] = 'smoke'
    for checkout in (before, after):
        (checkout / sample.ROUTE).write_text(json.dumps(route))
    source = after / sample.GAME / 'player/player.tscn'; original = source.read_bytes()
    repo = Path(__file__).resolve().parents[1]
    patch = repo / 'agents/fixtures/fix-collision-mask.patch'
    if case == 'exhausted':
        patch = root / 'bad.patch'
        patch.write_text((repo / 'agents/fixtures/fix-collision-mask.patch').read_text().replace(
            '+collision_mask = 30', '+collision_mask = 12'))
    boot = root / 'bootstrap'; boot.mkdir()
    (boot / 'sitecustomize.py').write_text('from tests.repair_cli_fixture import bootstrap\nbootstrap()\n')
    env = {k:v for k,v in os.environ.items() if not k.startswith('EXPECTRAIL_') and k != 'MODEL_API_KEY'}
    env.update({k:v for k,v in os.environ.items() if k in ('EXPECTRAIL_GODOT','EXPECTRAIL_TOOLS')})
    env['EXPECTRAIL_SANDBOX'] = 'require' if isolated else 'off'
    env['PYTHONPATH'] = str(boot) + os.pathsep + str(repo)
    jobs = root / 'jobs'
    def run(args, name):
        with (root / (name+'.stdout')).open('w') as stdout, (root / (name+'.stderr')).open('w') as stderr:
            proc = subprocess.run([sys.executable, '-m', 'expectrail.cli', *args], env=env,
                                  stdout=stdout, stderr=stderr, timeout=600)
        return proc.returncode, (root / (name+'.stdout')).read_text()
    argv = ['verify', '--head', str(after), '--base', str(before), '--game', sample.GAME,
            '--routes', sample.ROUTE, '--specs', sample.SPECS, '--jobs-root', str(jobs),
            '--execution-class', 'isolated' if isolated else 'diagnostic', '--json']
    if case == 'auto': argv += ['--auto-fix', '--auto-fix-fixture', str(patch), '--auto-fix-attempts', '1']
    code, text = run(argv, 'verify')
    assert code == 1, (code, text, (root/'verify.stderr').read_text())
    parent = json.loads(text); assert parent['decision'] == 'reject'
    if case != 'auto':
        code, text = run(['repair', parent['id'], '--jobs-root', str(jobs), '--fixture', str(patch),
                          '--attempts', '2' if case == 'exhausted' else '1'], 'repair')
        assert code == (2 if case == 'exhausted' else 0), (code, text)
    paths = list((jobs/'jobs'/parent['id']).glob('repair-*/repair-run.json'))
    assert len(paths) == 1
    doc = contracts.load_strict(paths[0], 'repair-run')
    assert doc['fixer']['source'] == 'fixture' and not doc['fixer']['sandboxed']
    findings = []
    for attempt in doc['attempts']:
        child = record.read_record(jobs/'jobs'/attempt['job']/'output/findings.json')
        assert child['observers']['rule'] == 'both'
        assert child['observers']['visual']['provider'] == TraceSegments.provider
        assert child['isolation']['required'] == isolated
        if isolated: assert child['isolation']['sandboxed'] == child['isolation']['replays'] > 0
        findings.append(child)
    if case == 'exhausted':
        assert doc['result']['decision'] == 'needs-review' and doc['stop']['reason'] == 'attempts-exhausted'
        assert [a['decision'] for a in doc['attempts']] == ['reject','reject']
    else:
        assert doc['result']['decision'] == 'accept' and findings[-1]['repair']['demonstrated'] > 0
        assert doc['result']['job'] != parent['id']
    assert source.read_bytes() == original
    proof = {'case':case, 'realEngine':True, 'isolated':isolated,
        'observer':'trace fixture; not independent vision', 'modelCalls':0,
        'parentDecision':parent['decision'], 'result':doc['result']['decision'],
        'stop':doc['stop']['reason'], 'attempts':[a['decision'] for a in doc['attempts']],
        'demonstrated':[f['repair']['demonstrated'] for f in findings],
        'sourceUnchanged':True, 'patchSha256':doc['attempts'][-1]['patchSha256']}
    (root/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    return proof
