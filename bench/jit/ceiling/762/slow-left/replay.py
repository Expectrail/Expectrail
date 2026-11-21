"""Replay the frozen slow-left proposal and diagnostic on four local builds."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from difflib import unified_diff
from pathlib import Path

from expectrail.contracts import digest_v1
from expectrail.discovery.route_compiler import compile_route
from expectrail.jit import assess, do_nothing, intent, offer
from expectrail.jit.diff_map import withheld_map
from expectrail.jit.run import _default_runner, _evaluate, _probe_ids_for
from expectrail.trace.evaluator import evaluate
from expectrail.trace.normalize import from_run_dir
from expectrail.trace.signals import player_dx_px, player_screen_x_range_px

CASE = Path(__file__).resolve().parent
ROOT = CASE.parents[4]
PUBLIC = ROOT / 'bench/jit/public/slow-left'
OFFER = offer.CONTROL
REPS = 3


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def frozen_plan(out: Path, game: Path, profile: dict, report: str):
    for recorded in (CASE / 'frozen.sha256').read_text(encoding='utf-8').splitlines():
        checksum, filename = recorded.split()
        if sha((CASE / filename).read_bytes()) != checksum:
            raise ValueError(f'Frozen hash differs for {filename}')

    library = offer.library(profile['actions'], OFFER, report, profile=profile, game=game)
    dmap = withheld_map(library)
    answer = intent.from_proposal(CASE / intent.PROPOSAL_NAME, offer=OFFER, candidate=intent.WITHHELD)
    proposal = answer(report, '', dmap, profile, library)
    entries = [(entry, _probe_ids_for(entry, library, set(dmap['probeIds']))) for entry in proposal['candidates']]
    mirror = read_json(CASE / 'mirror.json')
    entries.append((mirror['entry'], [mirror['probe'], mirror['mirror']['id']]))
    probes = {probe['id']: probe for probe in [*library, mirror['mirror']]}
    route_dir = out / 'frozen-routes'
    route_dir.mkdir()
    routes = {}
    for pid in sorted({pid for _, ids in entries for pid in ids}):
        probe = probes[pid]
        route = compile_route(probe['program'], name=pid, description=probe['description'],
                              actions=offer.route_actions(profile, probe))
        path = route_dir / f'{pid}.json'
        write_json(path, route)
        routes[pid] = route, path
    return entries, routes


def build_arms(out: Path, game: Path, profile: dict) -> tuple[dict, str]:
    control = do_nothing.control(game, profile, 'player')
    control_patch = out / 'do-nothing.patch'
    control_patch.write_text(control['patchText'], encoding='utf-8')
    comment_patch = out / 'comment-only.patch'
    script = 'player/player.gd'
    clean_lines = (game / script).read_text(encoding='utf-8').splitlines(keepends=True)
    comment_patch.write_text(''.join(unified_diff(
        clean_lines, [*clean_lines, '\n# Comment-only replay control for issue #762.\n'],
        fromfile=f'a/{script}', tofile=f'b/{script}',
    )), encoding='utf-8')
    return {
        'clean': [],
        'defect': [PUBLIC / 'defect.patch'],
        'do-nothing': [control_patch],
        'comment-only': [comment_patch],
    }, control['mode']


def run_arm(arm, patches, mode, out, runner, entries, routes):
    def replay(task):
        index, pid = task
        route, path = routes[pid]
        run_dir = out / 'replays' / arm / str(index) / pid
        runner(path, run_dir, patches=patches)
        ep = from_run_dir(run_dir, route, episode_id=f'{arm}-{pid}-{index}')
        manifest = read_json(run_dir / 'replay.json')
        return index, pid, ep, {
            'player_dx_px': player_dx_px(ep),
            'player_screen_x_range_px': player_screen_x_range_px(ep),
            'firstSample': ep['samples'][0]['player'],
            'coverage': ep['completeness'],
            'traceSha256': manifest['trace']['sha256'],
            'patchSha256': manifest['game']['patchSha256'],
            'engine': manifest['engine'],
            'isolation': manifest['isolation'],
        }

    rows = [{'probes': {}, 'checks': {}} for _ in range(REPS)]
    episodes = [{} for _ in rows]
    tasks = [(i, pid) for i in range(1, REPS + 1) for pid in routes]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for index, pid, ep, detail in pool.map(replay, tasks):
            episodes[index - 1][pid] = ep
            rows[index - 1]['probes'][pid] = detail

    for row, eps in zip(rows, episodes):
        for entry, ids in entries:
            spec = entry['spec']
            verdict = evaluate(spec, *[eps[pid] for pid in ids])
            if verdict['result'] != _evaluate(entry, ids, eps):
                raise ValueError(f'Generator and trace evaluator disagree for {spec["id"]}')
            info = {key: verdict[key] for key in ('result', 'applicable', 'coverageComplete', 'triggeredCount',
                                                  'evaluatedCount', 'metrics', 'diagnostics')}
            if arm == 'do-nothing':
                info['controlResult'], info['controlReason'] = do_nothing.judge(entry, ids, eps, _evaluate, mode)
                info['groundedResult'] = _evaluate(entry, ids, do_nothing.grounded(eps))
            row['checks'][spec['id']] = info
    return rows


def outcomes(rows: list[dict], arm: str, spec_id: str) -> list[str]:
    key = 'controlResult' if arm == 'do-nothing' else 'result'
    return [row['checks'][spec_id][key] for row in rows]


def diagnostic_conjunction(parts: tuple[str, ...]) -> str:
    if 'fail' in parts:
        return 'fail'
    if all(part == 'pass' for part in parts):
        return 'pass'
    return 'undecided'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='New directory for replay logs and raw-results.json')
    out = parser.parse_args().out.resolve()
    out.mkdir(parents=True)
    os.environ.setdefault('EXPECTRAIL_GODOT_CACHE', str(out / 'cache'))

    profile = read_json(ROOT / 'discovery/platformer.profile.json')
    game = ROOT / profile['game']['path']
    report = (PUBLIC / 'report.txt').read_text(encoding='utf-8')
    entries, routes = frozen_plan(out, game, profile, report)
    arms, mode = build_arms(out, game, profile)
    runner = _default_runner(game)
    result = {
        'routes': {pid: {'routeSha256': digest_v1(route), 'ticks': route['ticks'], 'seed': route['seed'],
                         'events': route['events']} for pid, (route, _) in routes.items()},
        'arms': {},
        'summary': {},
    }
    for arm, patches in arms.items():
        result['arms'][arm] = run_arm(arm, patches, mode, out, runner, entries, routes)
        print(f'Finished {arm}: {REPS} runs on {len(routes)} routes', flush=True)
        write_json(out / 'raw-results.json', result)

    for entry, _ in entries:
        spec = entry['spec']
        by_arm = {arm: outcomes(rows, arm, spec['id']) for arm, rows in result['arms'].items()}
        result['summary'][spec['id']] = {
            'source': entry['source'],
            'outcomes': by_arm,
            'controlOutcome': assess.do_nothing(by_arm['do-nothing']),
            'legacyValidityAgainstBase': assess.validity(by_arm['clean'], {'base': by_arm['defect']},
                                                         REPS, by_arm['do-nothing']),
            'reportRelevant': assess.relevant(spec['operation'], report),
        }
    mirror_id = read_json(CASE / 'mirror.json')['entry']['spec']['id']
    components = ('jit-slow-left-travel-floor', 'jit-slow-left-right-travel-floor', mirror_id)
    result['compoundDiagnostic'] = {
        arm: [diagnostic_conjunction(parts) for parts in zip(*(outcomes(rows, arm, sid) for sid in components))]
        for arm, rows in result['arms'].items()
    }
    write_json(out / 'raw-results.json', result)


if __name__ == '__main__':
    main()
