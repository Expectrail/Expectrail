"""Run the public #531 command measurement on committed disposable project copies."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
import json
from multiprocessing import Manager
from pathlib import Path
import shutil
import subprocess

from harness import tree
from harness.run import apply_patches, run
from expectrail.route import read_trace
from .command import batch, environment, ingest, write_report
from .producer import FALL, write_json
from .scale import REPO, public_builds


def prepare(root, build):
    project = root / 'projects' / build['id']
    if project.exists():
        return project
    tree.copy(REPO / 'game/platformer', project, skip=tree.GODOT_SKIP)
    if build['patch']:
        apply_patches(project, [REPO / build['patch']])
    config = {'format': 'expectrail.project/v1', 'adapter': 'godot',
              'entryScene': 'res://game_singleplayer.tscn', 'viewport': [800, 480],
              'physicsTicksPerSecond': 120, 'captureFps': 60,
              'inputActions': ['move_left', 'move_right', 'jump', 'shoot'],
              'bindings': {'player': {'node': 'Level/Player', 'texture': 'res://player/robot.webp'}},
              'routes': ['routes/wait.json'], 'approvedContracts': ['checks/ground.json']}
    write_json(project / 'expectrail.project.json', config)
    write_json(project / 'routes/wait.json', {'format': 'expectrail.route/v0', 'name': 'wait', 'ticks': 240, 'events': []})
    (project / 'checks').mkdir()
    shutil.copyfile(REPO / 'agents/specs/player-stays-above-ground.json', project / 'checks/ground.json')
    subprocess.run(['git', 'init', '-q', str(project)], check=True)
    subprocess.run(['git', '-C', str(project), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(project), '-c', 'user.name=Expectrail', '-c',
                    'user.email=local@example.invalid', '-c', 'commit.gpgsign=false',
                    'commit', '-qm', 'Disposable public playtest build'], check=True)
    return project


def measure(task):
    root, build, godot, count, start, semaphore = task
    project = prepare(root, build)
    result = batch(project, root / 'builds' / build['id'], godot,
                   start=start, count=count, viewport=[800, 480], compact_replays=True, ingest_jobs=4, ingest_semaphore=semaphore)
    return {'build': build, 'reports': result['reports'], 'grouped': result['groupedCount'], 'outcomes': result['outcomes']}


def false_reports(root, godot):
    project = root / 'projects/clean'
    route = {'format': 'expectrail.route/v0', 'name': 'false-idle', 'ticks': 240, 'events': []}
    folder = root / 'false-reports'
    write_json(folder / 'route.json', route)
    import os
    before = dict(os.environ)
    try:
        os.environ.clear(); os.environ.update(environment(folder, godot))
        run(folder / 'route.json', folder / 'calibration', game=project, godot=godot, capture_frames=False)
    finally:
        os.environ.clear(); os.environ.update(before)
    point = read_trace(folder / 'calibration/trace.json', 240, 120)['rows'][99]['player']
    doc = {'format': 'expectrail.playtest-report/v1', 'id': 'handwritten-false-idle',
           'producer': {'name': 'handwritten', 'version': '1'},
           'target': {'commit': subprocess.check_output(['git', '-C', str(project), 'rev-parse', 'HEAD'], text=True).strip()},
           'route': route, 'bug': FALL,
           'fault': {'preFaultTick': 99, 'faultTick': 100,
                     'anchor': {'object': 'player', 'x': point[0], 'y': point[1], 'tolerancePx': 2}}}
    wrong = copy.deepcopy(doc)
    wrong['id'] = 'handwritten-false-anchor'
    wrong['fault']['anchor']['x'] += 10000
    results = []
    for item in (doc, wrong):
        path = folder / (item['id'] + '.json')
        write_report(path, item)
        results.append(ingest(path, project, folder / 'intakes', godot, compact_replays=True))
    write_json(folder / 'results.json', results)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--godot', required=True, type=Path)
    parser.add_argument('--count', type=int, default=200)
    parser.add_argument('--start', type=int, default=10000)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--only', help='one public build ID (smoke/debug)')
    args = parser.parse_args(argv)
    root, godot = args.out.resolve(), args.godot.resolve()
    builds = public_builds()
    if args.only:
        builds = [b for b in builds if b['id'] == args.only]
        if not builds:
            parser.error('unknown public build')
    write_json(root / 'build-manifest.json', builds)
    results = []
    with Manager() as manager, ProcessPoolExecutor(max_workers=args.jobs) as pool:
        semaphore = manager.BoundedSemaphore(4)
        futures = [pool.submit(measure, (root, b, godot, args.count, args.start, semaphore)) for b in builds]
        for future in as_completed(futures):
            results.append(future.result())
            write_json(root / 'measurement.json', sorted(results, key=lambda r: r['build']['id']))
    if not args.only:
        false_reports(root, godot)


if __name__ == '__main__':
    main()
