"""Replay the frozen #762 slides-after-stop proposal with no intent model."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

from expectrail.contracts import digest_v1
from expectrail.discovery.route_compiler import compile_route
from expectrail.jit import assess, do_nothing, intent, offer
from expectrail.jit.run import _evaluate
from expectrail.trace.evaluator import evaluate
from expectrail.trace.normalize import from_run_dir
from harness.run import run

CASE = Path(__file__).resolve().parent
ROOT = CASE.parents[4]
GAME = ROOT / 'game/platformer'
PUBLIC = ROOT / 'bench/jit/public/slides-after-stop'
HARMLESS_SHA = '48a16859864aa88fdbfd94bb0a508b9764bacf19fb6ef53def4d6f9b22b16b65'


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_proposal(work):
    freeze = read_json(CASE / 'freeze.json')
    path = CASE / 'jit-proposal.json'
    if sha(path) != freeze['proposalSha256']:
        raise ValueError('the proposal differs from the pre-replay freeze')
    report = (PUBLIC / 'report.txt').read_text()
    profile = read_json(ROOT / 'discovery/platformer.profile.json')
    probes = offer.library(profile['actions'], offer.CONTROL, report, profile=profile)
    load = intent.from_proposal(path, offer=offer.CONTROL, candidate=intent.WITHHELD)
    answer = load(report, '', {}, profile, probes)
    needed = {e['applies'][side] for e in answer['candidates'] for side in ('left', 'right')}
    routes = {}
    route_dir = work / 'routes'
    route_dir.mkdir()
    for p in probes + answer['probes']:
        pid = p['id']
        if pid in needed:
            route = compile_route(p['program'], name=pid, description=p['description'],
                                  actions=offer.route_actions(profile, p))
            route_path = route_dir / f'{pid}.json'
            write_json(route_path, route)
            routes[pid] = (route_path, route)
    return freeze, profile, answer['candidates'], routes


def direct_trace(episode, bound):
    samples = {s['tick']: s for s in episode['samples']}
    start = bound['heldFromTick']
    end = bound['tailToTick']
    if any(tick not in samples or samples[tick]['player'] is None for tick in range(start, end + 1)):
        return {'outcome': 'insufficient_observation'}
    x = {tick: s['player'][0] for tick, s in samples.items() if s['player'] is not None}
    release = next(i['tick'] for i in episode['inputs'] if i['action'] == 'move_right' and not i['pressed'])
    held = round(x[bound['heldToTick']] - x[start], 3)
    tail = [x[tick] for tick in range(bound['tailFromTick'], end + 1)]
    late_extent = round(max(tail) - min(tail), 3)
    moved = [tick for tick in range(release, max(x) + 1) if tick in x and tick - 1 in x and x[tick] != x[tick - 1]]
    return {'outcome': 'pass' if held >= bound['heldMinProgressPx'] and late_extent <= bound['tailMaxExtentPx'] else 'fail',
            'releaseTick': release, 'heldProgressPx': held, 'tailExtentPx': late_extent,
            'tailFirstXPx': tail[0], 'tailLastXPx': tail[-1],
            'finalXPx': x[max(x)], 'lastObservedHorizontalChangeTick': moved[-1] if moved else None}


def arm_replays(name, patches, routes, work, godot, workers):
    def replay(rep, pid):
        folder = work / name / str(rep) / pid
        route_path, route = routes[pid]
        try:
            record = run(route_path, folder, patches=patches, game=GAME, godot=godot, capture_frames=False)
            if record['route']['sha256'] != sha(route_path):
                raise ValueError('harness replayed a different route')
            if sha(folder / 'trace.json') != record['trace']['sha256']:
                raise ValueError('harness trace hash changed')
            episode = from_run_dir(folder, route, episode_id=f'{name}-{rep}-{pid}')
            raw = {k: record[k] for k in ('game', 'engine', 'isolation')}
            raw.update(traceSha256=record['trace']['sha256'], replaySha256=digest_v1(record))
            return rep, pid, episode, raw
        except (Exception, SystemExit) as exc:
            return rep, pid, None, {'error': f'{type(exc).__name__}: {str(exc).splitlines()[0]}'}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        runs = [pool.submit(replay, rep, pid) for rep in range(1, 4) for pid in routes]
        return [job.result() for job in runs]


def outcomes(rows, candidates, bound, *, control_mode=None, harmless=False):
    episodes = defaultdict(dict)
    recordings = defaultdict(dict)
    for rep, pid, episode, raw in rows:
        episodes[rep][pid] = episode
        recordings[rep][pid] = raw
    checks = defaultdict(list)
    auxiliary = []
    for rep, eps in episodes.items():
        for e in candidates:
            spec, applies = e['spec'], e['applies']
            ids = [applies['left'], applies['right']]
            left, right = (eps[pid] for pid in ids)
            if left is None or right is None:
                checks[spec['id']].append({'result': 'execution_error'})
                continue
            verdict = evaluate(spec, left, right)
            if control_mode:
                result, reason = do_nothing.judge(e, ids, eps, _evaluate, control_mode)
                verdict.update(recordedResult=verdict['result'], result=result, controlReason=reason)
            elif harmless:
                verdict.update(result=assess.harmless_repetition(spec, [verdict]))
            checks[spec['id']].append(verdict)
        episode = eps[bound['probe']]
        auxiliary.append(direct_trace(episode, bound) if episode else {'outcome': 'execution_error'})
    return {'checks': dict(checks), 'auxiliaryTraceObservation': auxiliary, 'replays': dict(recordings)}


def summarize(candidates, arms, report):
    rows = {}
    for e in candidates:
        spec = e['spec']
        sid = spec['id']
        op = spec['operation']
        results = {arm: [v['result'] for v in row['checks'][sid]] for arm, row in arms.items()}
        margins = []
        for verdict in arms['clean']['checks'][sid]:
            if 'metrics' in verdict:
                m = verdict['metrics']
                delta = m['right'] - m['left']
                margins.append(m['toleranceAbs'] - abs(delta) if op['comparator'] == 'eq' else delta - m['toleranceAbs'])
        rows[sid] = {'rawOutcomes': results,
                     'tightestCleanClearancePx': min(margins) if margins else None,
                     'doNothing': assess.do_nothing(results['do-nothing']),
                     'harmless': assess.harmless_outcome(results['clean'], results['harmless']),
                     'currentAssessorRelevance': assess.relevant(op, report)}
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True, help='new temporary work directory')
    parser.add_argument('--godot', type=Path, required=True, help='pinned Godot 4.7.2 executable')
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=False)
    freeze, profile, candidates, routes = load_proposal(args.work)
    control = do_nothing.control(GAME, profile, 'player')
    control_patch = args.work / 'do-nothing.patch'
    control_patch.write_text(control['patchText'])
    harmless = ROOT / 'agents/fixtures/operators/comment-only.patch'
    if sha(harmless) != HARMLESS_SHA:
        raise ValueError('the registered harmless operator changed')
    patch_sets = {'clean': [], 'actual-defect': [PUBLIC / 'defect.patch'],
                  'do-nothing': [control_patch], 'harmless': [harmless]}
    arms = {}
    for name, patches in patch_sets.items():
        rows = arm_replays(name, patches, routes, args.work, args.godot, args.workers)
        arms[name] = outcomes(rows, candidates, freeze['auxiliaryTraceObservation'],
                              control_mode=control['mode'] if name == 'do-nothing' else None,
                              harmless=name == 'harmless')
        write_json(args.work / f'{name}-results.json', arms[name])
        print(name, {sid: [v['result'] for v in verdicts]
                     for sid, verdicts in arms[name]['checks'].items()}, flush=True)
    report = (PUBLIC / 'report.txt').read_text()
    summary = summarize(candidates, arms, report)
    write_json(args.work / 'results.json', {'proposalSha256': freeze['proposalSha256'],
                                          'routes': {pid: {'route': route, 'routeSha256': digest_v1(route)}
                                                     for pid, (_, route) in routes.items()},
                                          'doNothingMode': control['mode'],
                                          'summary': summary, 'arms': arms})
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
