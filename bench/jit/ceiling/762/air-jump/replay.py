"""Replay the frozen air-jump proposal on four arms, outside the JIT early-stop stages."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from expectrail.contracts import digest_v1
from expectrail.discovery.route_compiler import compile_route
from expectrail.jit import assess, do_nothing, intent, offer
from expectrail.jit.run import _evaluate
from expectrail.repro.control_form import form
from expectrail.trace.evaluator import evaluate
from expectrail.trace.normalize import from_run_dir
from expectrail.trace.signals import (
    IMPULSE_PX_PER_TICK, air_jumps, airborne_episodes, max_rise_px, player_samples,
)
from harness.run import run, tree_digest

cli = argparse.ArgumentParser(description=__doc__)
cli.add_argument('--godot', type=Path, required=True, help='path to the pinned Godot 4.7.2 binary')
cli.add_argument('--work', type=Path, required=True, help='directory for replay traces and results.json')
args = cli.parse_args()
case = Path(__file__).resolve().parent
root = case.parents[4]
game = root / 'game/platformer'
engine = args.godot.resolve(strict=True)
scratch = args.work.resolve()
if scratch.is_relative_to(root):
    cli.error('--work must be outside the game checkout')
scratch.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('EXPECTRAIL_GODOT_CACHE', str(scratch / 'cache'))
proposal_path = case / 'jit-proposal.json'
report = (root / 'bench/jit/known/air-jump/report.txt').read_text()
profile = json.loads((root / 'discovery/platformer.profile.json').read_text())

def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()

assert sha(proposal_path) == (case / 'SHA256SUMS').read_text().split()[0]
profile_probes = offer.library(profile['actions'], offer.CONTROL, report, profile=profile, game=game)
parse = intent.from_proposal(proposal_path, offer=offer.CONTROL, candidate=intent.WITHHELD)
parsed = parse(report, '', {}, profile, profile_probes)
probes = {p['id']: p for p in profile_probes + parsed['probes']}
checks = {entry['spec']['id']: entry for entry in parsed['candidates']}
plans = {
    name: [entry['applies']['left'], entry['applies']['right']]
    if entry['applies']['kind'] == 'pair' else entry['applies']['ids']
    for name, entry in checks.items()
}
stock = {p['id']: p for p in offer.library(profile['actions'], offer.BASELINE, report, profile=profile, game=game)}
routes = {}
for pid in sorted({pid for ids in plans.values() for pid in ids}):
    probe = probes[pid]
    if pid in stock:
        assert stock[pid] == probe
    route = compile_route(probe['program'], name=pid, description=probe['description'], actions=profile['actions'])
    path = scratch / (pid + '.json')
    route_text = json.dumps(route, indent=1) + '\n'
    if path.exists():
        assert path.read_text() == route_text
    else:
        path.write_text(route_text)
    routes[pid] = (route, path)

registered_comment = root / 'agents/fixtures/operators/comment-only.patch'
assert sha(registered_comment) == '48a16859864aa88fdbfd94bb0a508b9764bacf19fb6ef53def4d6f9b22b16b65'
player_control = do_nothing.control(game, profile, 'player')
assert player_control['mode'] == 'frozen'
frozen_patch = scratch / 'frozen-player.patch'
frozen_patch.write_text(player_control['patchText'])
arms = {
    'clean': [],
    'defect': [root / 'bugs/reported/air-jump.patch'],
    'frozen': [frozen_patch],
    'comment-only': [registered_comment],
}
clean_tree = tree_digest(game)

def launch_evidence(ep):
    presses = [item['tick'] for item in ep['inputs'] if item['action'] == 'jump' and item['pressed']]
    spans, _ = airborne_episodes(ep)
    samples = {s['tick']: s for s in player_samples(ep)}
    for sp in spans:
        start = sp['start']
        if (start - 1 not in presses or not samples[start - 1]['onFloor']
                or samples[start]['player'][1] >= samples[start - 1]['player'][1]):
            continue
        end = sp['end'] if sp['end'] is not None else max(samples)
        kicks = {}
        for t in range(start + 1, end):
            if not all(s in samples for s in (t, t - 1, t - 2)):
                continue
            now, prev, before = (samples[s]['player'][1] for s in (t, t - 1, t - 2))
            impulse = (now - prev) - (prev - before)
            if impulse < -IMPULSE_PX_PER_TICK:
                kicks[str(t)] = round(impulse, 3)
        return {
            'launchTick': start,
            'launchUpwardPx': round(samples[start - 1]['player'][1] - samples[start]['player'][1], 3),
            'landingTick': sp['end'],
            'airborneJumpPressTicks': [t for t in presses if start <= t < end],
            'upwardImpulsePxPerTick': kicks,
        }
    return None

results = {
    'proposalSha256': sha(proposal_path),
    'reportSha256': sha(root / 'bench/jit/known/air-jump/report.txt'),
    'gameTree': clean_tree,
    'engineSha256': sha(engine),
    'routes': {pid: {'digest': digest_v1(r), 'fileSha256': sha(path), 'ticks': r['ticks'],
                     'jumpPressTicks': [e['tick'] for e in r['events'] if e['action'] == 'jump' and e['pressed']]}
               for pid, (r, path) in routes.items()},
    'patchSha256': {arm: sha(patches[0]) if patches else None for arm, patches in arms.items()},
    'episodes': {},
    'checks': {name: {'form': form(entry['spec']), 'specSha256': digest_v1(entry['spec']), 'runs': {}}
               for name, entry in checks.items()},
}
all_rows = results['episodes']
for arm, patches in arms.items():
    all_rows[arm] = {}
    episodes = {}
    for pid, (route, path) in routes.items():
        all_rows[arm][pid] = []
        for rep in range(1, 4):
            folder = scratch / arm / pid / str(rep)
            if (folder / 'replay.json').is_file() and (folder / 'trace.json').is_file():
                rec = json.loads((folder / 'replay.json').read_text())
            else:
                rec = run(path, folder, game=game, godot=engine, patches=patches, capture_frames=False)
            assert rec['game']['tree'] == clean_tree
            assert rec['game']['patchSha256'] == results['patchSha256'][arm]
            assert rec['route']['sha256'] == sha(path)
            assert rec['trace']['sha256'] == sha(folder / 'trace.json')
            ep = from_run_dir(folder, route, episode_id=f'{arm}-{pid}-{rep}')
            episodes[pid, rep] = ep
            all_rows[arm][pid].append({
                'traceSha256': rec['trace']['sha256'],
                'airJumps': air_jumps(ep),
                'maxRisePx': max_rise_px(ep),
                'inputBoundLaunch': launch_evidence(ep),
            })
            results.setdefault('isolation', rec['isolation'])
            results.setdefault('engine', rec['engine'])
            assert results['engine'] == rec['engine']
            assert results['isolation'] == rec['isolation']
            print(arm, pid, rep, air_jumps(ep), max_rise_px(ep), flush=True)
    for name, entry in checks.items():
        ids = plans[name]
        spec = entry['spec']
        repetitions = []
        for rep in range(1, 4):
            eps = {pid: episodes[pid, rep] for pid in ids}
            verdicts = [evaluate(spec, *eps.values())] if entry['applies']['kind'] == 'pair' else [
                evaluate(spec, ep) for ep in eps.values()
            ]
            if arm == 'frozen':
                outcome, reason = do_nothing.judge(entry, ids, eps, _evaluate, player_control['mode'])
            else:
                outcome, reason = _evaluate(entry, ids, eps), None
            repetitions.append({'outcome': outcome, 'reason': reason, 'verdicts': [
                {key: v[key] for key in ('result', 'triggeredCount', 'evaluatedCount', 'coverageComplete',
                                         'applicable', 'metrics', 'evidence')}
                for v in verdicts
            ]})
        results['checks'][name]['runs'][arm] = repetitions

def outcomes(check, arm):
    return [r['outcome'] for r in results['checks'][check]['runs'][arm]]

for name, row in results['checks'].items():
    row['replayAssessorValidity'] = assess.validity(outcomes(name, 'clean'), {'base': outcomes(name, 'defect')},
                                                    do_nothing_runs=outcomes(name, 'frozen'))
    row['frozenArm'] = assess.do_nothing(outcomes(name, 'frozen'))

def conjunction(demand, ceiling):
    if 'fail' in (demand, ceiling):
        return 'fail'
    return 'pass' if demand == ceiling == 'pass' else 'indeterminate'

demand, ceiling = 'jit-air-jump-demand', 'jit-air-jump-ceiling'
results['manualConjunction'] = {
    arm: [conjunction(d, c) for d, c in zip(outcomes(demand, arm), outcomes(ceiling, arm))]
    for arm in arms
}
bad = json.loads(proposal_path.read_text())
bad['candidates'] = [bad['candidates'][0]]
bad['candidates'][0]['spec']['operation'] = {
    'type': 'all_of',
    'operations': [checks[demand]['spec']['operation'], checks[ceiling]['spec']['operation']],
}
bad_path = scratch / 'unsupported-conjunction.json'
bad_path.write_text(json.dumps(bad) + '\n')
try:
    intent.from_proposal(bad_path, offer=offer.CONTROL, candidate=intent.WITHHELD)(report, '', {}, profile, profile_probes)
except intent.IntentUnavailable as exc:
    results['compoundParserResult'] = str(exc)
else:
    raise AssertionError('compound candidate unexpectedly accepted')
(scratch / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
for name, row in results['checks'].items():
    print(name, {arm: outcomes(name, arm) for arm in arms}, row['replayAssessorValidity'])
print('manual', results['manualConjunction'])
print('native compound', results['compoundParserResult'])
