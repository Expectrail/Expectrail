"""Capture pinned outside games without a key, or judge the saved evidence without a game."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from expectrail import contracts
from expectrail.gate import record, verify
from tools import outside_trial as trial


def variants(project):
    return {'pinned': None, **{change['name']: change for change in project.get('changes', [])}}


def routes(project):
    return sorted((trial.REPO / project['routes']).glob('*.json'))


def directory(path, expected):
    if path.is_symlink() or not path.is_dir() or {p.name for p in path.iterdir()} != set(expected):
        raise ValueError(f'{path.name}: unexpected or missing capture files')


def read(path, limit):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'{path.name}: expected a regular data file')
    return record.read_bytes_capped(path, limit, path.name)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def capture_id(project, data):
    """Bind the project, variant and route to each replay record through a separate job output."""
    cases = variants(project)
    paths = routes(project)
    if not paths or 'pinned' in [c['name'] for c in project.get('changes', [])]:
        raise ValueError('capture requires routes and distinct variant names')
    directory(data, cases)
    ids = {}
    for case in cases:
        directory(data / case, [p.stem for p in paths])
        ids[case] = {}
        for path in paths:
            folder = data / case / path.stem
            directory(folder, ('replay.json', 'trace.json', 'frames'))
            ids[case][path.name] = sha(read(folder / 'replay.json', 1024 * 1024))
    return contracts.digest({'project': project['name'], 'commit': project['commit'], 'runs': ids})


def saved_run(folder, route):
    data = read(folder / 'replay.json', 1024 * 1024)
    replay = record.strict_loads(data.decode())
    contracts.validate(replay, 'replay')
    cap = replay['capture']
    count = cap['frames']
    isolation = replay.get('isolation') or {}
    route_data = route.read_bytes()
    expected_route = {'name': json.loads(route_data)['name'], 'sha256': sha(route_data)}
    if (replay['route'] != expected_route or replay['engine']['name'] != 'godot'
            or cap['fps'] != verify.CAPTURE_FPS or cap['pattern'] != 'frames/f%08d.png'
            or isolation.get('mode') != 'require' or not record.isolation_summary([isolation], True)['sandboxed']):
        raise ValueError('replay does not record the required route, engine, frame format and sandbox')
    if not 0 < count <= 8192 or count != len(replay['frameSha256']):
        raise ValueError('invalid recorded frame count')
    trace_bytes = read(folder / 'trace.json', 64 * 1024 * 1024)
    if replay.get('trace') != {'path': 'trace.json', 'sha256': sha(trace_bytes)}:
        raise ValueError('trace differs from replay.json')
    trace = record.strict_loads(trace_bytes.decode())
    contracts.validate(trace, 'trace')
    if trace['physicsTicksPerSecond'] != cap.get('physicsTicksPerSecond'):
        raise ValueError('trace clock differs from replay.json')
    frames = folder / 'frames'
    directory(frames, (f'f{i:08d}.png' for i in range(count)))
    for index, digest in enumerate(replay['frameSha256']):
        png = read(frames / f'f{index:08d}.png', 32 * 1024 * 1024)
        if sha(png) != digest or not png.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError(f'frame {index} differs from replay.json or is not a PNG')
    return {'tree': replay['game']['tree'], 'trace': trace, 'framesDir': frames,
            'replaySha256': sha(data), 'isolation': isolation}


def capture(project, out):
    """Publish only completed captures. The fetched checkout is outside the upload directory."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        tmp = Path(tmp)
        source = trial.fetch(project, tmp / 'sources')
        data = tmp / 'captures'
        data.mkdir()
        for case, change in variants(project).items():
            checkout = trial.lay_out(project, source, tmp / 'checkouts', change)
            tree = verify.game_tree(checkout / 'project')
            stage = tmp / 'stage'
            rows = trial.capture(project, checkout, stage, timeout=900, sandbox='require')
            if not rows or any(row['exit'] or not row['frames'] for row in rows):
                raise ValueError(f'{case}: sandboxed capture failed')
            folder = stage / project['name']
            for path in routes(project):
                if saved_run(folder / path.stem, path)['tree'] != tree:
                    raise ValueError(f'{case}: replay names a different game tree')
            folder.rename(data / case)
        receipt = capture_id(project, data)
        data.rename(out)
    return receipt


def judge(project, data, receipt, out, observer):
    if capture_id(project, data) != receipt:
        raise ValueError('capture digest differs from the capture job output')
    cases = variants(project)
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        policy = Path(tmp).resolve()
        trees, runs = {}, {}
        # Check every run before the first model request. Policy comes from this trusted checkout.
        for case in cases:
            arm = policy / case
            shutil.copytree(trial.REPO / project['routes'], arm / 'routes')
            (arm / 'specs').mkdir()
            shutil.copyfile(trial.SPEC, arm / 'specs' / trial.SPEC.name)
            game = arm / 'project'
            for path in routes(project):
                run = saved_run(data / case / path.stem, path)
                if trees.setdefault(game, run['tree']) != run['tree']:
                    raise ValueError(f'{case}: routes name different game trees')
                runs[game, sha(path.read_bytes())] = run

        saved = verify.SavedReplays(trees, runs)
        for case, change in cases.items():
            start = time.monotonic()
            doc = verify.run_gate(repo=policy / case, base=policy / 'pinned' if change else None,
                                  game='project', routes=['routes/*.json'], specs='specs', out=out / case,
                                  work=policy / 'work' / case, replay=saved, rule=record.BOTH,
                                  require_sandbox=True, visual=observer, expectrail_commit=os.getenv('GITHUB_SHA'))
            decision = doc['decision']
            rows.append({'name': project['name'], 'commit': project['commit'], 'licence': project['licence'],
                         'change': change['name'] if change else None,
                         'what': change and change['what'], 'expect': change and change['expect'],
                         'exit': next(code for code, name in trial.VERDICTS.items() if name == decision),
                         'decision': decision, 'verdict': decision, 'seconds': round(time.monotonic() - start, 1),
                         'checks': doc['counts'], 'reasons': doc['reasons'],
                         'failures': [f['reason'] for f in doc['findings']]})
            (out / 'outside-trial.md').write_text(trial.markdown(rows))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('capture', 'judge'):
        sub = commands.add_parser(name)
        sub.add_argument('--project', required=True, choices=[p['name'] for p in trial.load_list()])
        sub.add_argument('--out', type=Path, required=True)
        if name == 'judge':
            sub.add_argument('--data', type=Path, required=True)
            sub.add_argument('--digest', required=True)
    args = parser.parse_args(argv)
    project = next(p for p in trial.load_list() if p['name'] == args.project)
    if args.out.exists():
        parser.error('--out must be a new folder')
    if args.command == 'capture':
        digest = capture(project, args.out)
        print(f'Capture SHA-256: {digest}')
        if output := os.getenv('GITHUB_OUTPUT'):
            with open(output, 'a') as handle:
                print(f'digest={digest}', file=handle)
        return 0

    from agents.sam_observations import CAP_ENV, MetaSamClient, sam_usage
    from expectrail.observers import FramesObserver

    cap = os.getenv(CAP_ENV, '')
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?', cap) or not 0 < float(cap) <= 2:
        parser.error(f'{CAP_ENV} must be a positive amount of at most 2 dollars')
    if not os.getenv('MODEL_API_KEY', '').strip():
        parser.error('MODEL_API_KEY is missing')
    args.out.mkdir(parents=True)
    before = sam_usage()
    try:
        judge(project, args.data, args.digest, args.out,
              FramesObserver(client=MetaSamClient(), name='sam', every=1))
    finally:
        used = {key: value - before[key] for key, value in sam_usage().items()}
        (args.out / 'spend.json').write_text(json.dumps(used, indent=2) + '\n')
        print(f"Spend at list price: ${used['reservedUsd']:.4f}, {used['requests']} requests, "
              f"{used['images']} images answered")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
