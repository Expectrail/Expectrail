"""Play bounded seeds, retain every report, and submit each to the real ingest CLI."""
from __future__ import annotations

import argparse
import copy
from contextlib import nullcontext
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

from . import producer
from .producer import write_json


def write_report(path, document):
    """Validate with the merged reader before creating any report file."""
    from expectrail.orchestrator import playtest
    playtest.check(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if playtest.load(path) != document:
            raise ValueError(f'existing report differs: {path}')
        return
    playtest.write(path, document)
    if playtest.load(path) != document:
        raise ValueError(f'report readback differs: {path}')


def report_documents(route, trace, commit, *, viewport=None):
    """Adapt main's unchanged observations to the current intake contract, in memory."""
    from expectrail.orchestrator import playtest
    result = []
    for legacy in producer.reports(route, trace, commit, viewport=viewport):
        payload = copy.deepcopy({k: v for k, v in legacy.items() if k != 'id'})
        anchor = payload['fault']['anchor']
        if anchor['object'] == 'Player':
            anchor['object'] = 'player'
        payload['producer']['version'] += '+ingest.1'
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False,
                                           separators=(',', ':')).encode()).hexdigest()
        document = {'id': 'playtest-' + digest[:32], **payload}
        playtest.check(document)
        result.append(document)
    return result


def play(project, commit, seed, out, *, ticks=1200, godot=None, viewport=None):
    """Use main's route/observations; write only contract-valid adapted reports."""
    from expectrail.route import input_map, read_trace
    from harness.run import run
    if out.exists():
        raise ValueError(f'output already exists: {out}')
    if viewport is not None:
        from .offscreen import viewport_size
        viewport = viewport_size(viewport)
    actions, rate, _ = input_map(project)
    route = producer.make_route(actions, seed, ticks)
    out.mkdir(parents=True)
    write_json(out / 'route.json', route)
    run(out / 'route.json', out / 'replay', game=project, godot=godot, capture_frames=False)
    trace = read_trace(out / 'replay/trace.json', ticks, rate)
    if trace.get('unknownActions'):
        raise ValueError('engine did not recognise every route action')
    documents = report_documents(route, trace, commit, viewport=viewport)
    for document in documents:
        write_report(out / 'reports' / (document['id'] + '.json'), document)
    write_json(out / 'summary.json', {'seed': seed, 'ticks': ticks, 'inputActions': actions,
                                     'reports': [d['id'] for d in documents]})
    return documents


def groups(documents):
    """Deterministic complete-link spatial grouping; never removes an intake."""
    result = []
    for doc in sorted(documents, key=lambda d: d['id']):
        anchor = doc['fault']['anchor']
        def matches(other):
            a = other['fault']['anchor']
            return (doc['target'] == other['target'] and doc['bug'] == other['bug']
                    and anchor['object'] == a['object']
                    and math.dist((anchor['x'], anchor['y']), (a['x'], a['y']))
                    <= min(anchor['tolerancePx'], a['tolerancePx']))
        for group in result:
            if all(matches(other) for other in group):
                group.append(doc)
                break
        else:
            result.append([doc])
    return [[doc['id'] for doc in group] for group in result]


def classify(status, precheck):
    evidence = status.get('reproduction') or {}
    reason = evidence.get('reason', '')
    if (status.get('phase') not in ('completed',)
            or any(d.get('code') in ('EXECUTION_TIMEOUT', 'BUDGET_STOP', 'WORKER_LOST', 'INTERNAL_ERROR')
                   for d in status.get('diagnostics', []))):
        outcome = 'job-error'
    elif evidence.get('kind') == 'approved' and evidence.get('checks'):
        outcome = 'approved'
    elif reason == 'anchor-desync':
        outcome = 'anchor-desync'
    elif reason == 'not-reproduced':
        outcome = 'not-reproduced'
    elif reason.startswith('playtest-reproduction-inconclusive:'):
        outcome = 'inconclusive'
    else:
        outcome = 'unclassified'
    reached = (len(precheck) == 3 and {r.get('run') for r in precheck} == {1, 2, 3}
               and all(r.get('coverage', {}).get('reached')
                       and all(v is True for v in r['coverage']['reached']) for r in precheck))
    return {'outcome': outcome, 'anchorReached3of3': bool(reached),
            'checks': evidence.get('checks', []), 'reason': reason,
            'decision': status.get('decision'), 'job': status.get('id'),
            'jobReasons': status.get('reasons', [])}


def environment(out, godot):
    # An allowlist prevents inherited visual/provider transports, tokens and budget flags.
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL', 'DISPLAY', 'XAUTHORITY',
           'LD_LIBRARY_PATH', 'SYSTEMROOT', 'TMPDIR', 'LP_NUM_THREADS') if k in os.environ}
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[2])
    env['EXPECTRAIL_GODOT'] = str(godot)
    env['EXPECTRAIL_GODOT_CACHE'] = str(out / 'shared-cache')
    for key, name in (('XDG_DATA_HOME', 'data'), ('XDG_CACHE_HOME', 'cache'), ('XDG_CONFIG_HOME', 'config')):
        folder = out / 'runtime' / name
        folder.mkdir(parents=True, exist_ok=True)
        env[key] = str(folder)
    return env


def compact(root):
    """Explicit opt-in after a terminal job: retain traces/logs, hash and remove PNGs."""
    removed = []
    for record in sorted(root.rglob('replay.json')):
        replay = json.loads(record.read_text())
        if (replay.get('format') != 'expectrail.replay/v0'
                or replay.get('capture', {}).get('pattern') != 'frames/f%08d.png'):
            continue
        for path in sorted((record.parent / 'frames').glob('f*.png')):
            data = path.read_bytes()
            removed.append({'path': path.relative_to(root).as_posix(), 'bytes': len(data),
                            'sha256': hashlib.sha256(data).hexdigest()})
            path.unlink()
        path = record.parent / 'trace.json'
        if path.exists():
            with gzip.open(str(path) + '.gz', 'wb', compresslevel=1) as stream:
                stream.write(path.read_bytes())
            path.unlink()
    write_json(root / 'removed-pngs.json', removed)


def ingest(report_path, project, out, godot, *, timeout=600, compact_replays=False):
    from expectrail.orchestrator.playtest import load
    document = load(report_path)
    dest = out / document['id']
    result_file = dest / 'result.json'
    if result_file.exists():
        saved = json.loads(result_file.read_text())
        if saved['reportSha256'] != hashlib.sha256(report_path.read_bytes()).hexdigest():
            raise ValueError('report changed since ingestion')
        return saved
    if dest.exists():
        raise ValueError(f'incomplete intake retained at {dest}; inspect it before retrying')
    dest.mkdir(parents=True)
    argv = [sys.executable, '-m', 'expectrail.cli', 'ingest', str(report_path),
            '--project', str(project), '--jobs-root', str(dest / 'store'),
            '--json', '--timeout', str(timeout)]
    write_json(dest / 'argv.json', argv)
    # The CLI waits for its real worker. Needs-review (exit 2) is a completed result.
    with (dest / 'stdout.json').open('w') as stdout, (dest / 'stderr.log').open('w') as stderr:
        env = environment(dest, godot)
        env['EXPECTRAIL_GODOT_CACHE'] = str(out / 'shared-cache')
        completed = subprocess.run(argv, env=env, stdout=stdout, stderr=stderr)
    statuses = list((dest / 'store/jobs').glob('*/status.json'))
    if len(statuses) != 1:
        raise ValueError(f'expected one real ingest job; exit {completed.returncode}; inspect {dest}')
    status = json.loads(statuses[0].read_text())
    precheck_file = statuses[0].parent / 'output/playtest-precheck.log'
    precheck = json.loads(precheck_file.read_text()) if precheck_file.exists() else []
    result = {**classify(status, precheck), 'exit': completed.returncode,
              'report': str(report_path),
              'reportSha256': hashlib.sha256(report_path.read_bytes()).hexdigest()}
    write_json(result_file, result)
    if compact_replays and status.get('phase') in ('completed', 'failed', 'cancelled'):
        compact(dest)
    return result


def batch(project, out, godot, *, start=10000, count=200, ticks=1200, viewport=None,
          timeout=1800, compact_replays=False, extra_reports=(), ingest_jobs=1, ingest_semaphore=None):
    project, out, godot = project.resolve(), out.resolve(), godot.resolve()
    if out == project or project in out.parents:
        raise ValueError('output must be outside the project (ingest snapshots it)')
    if not (type(count) is int and count > 0 and 0 <= start < start + count <= 2**32):
        raise ValueError('invalid seed range')
    commit = subprocess.check_output(['git', '-C', str(project), 'rev-parse', 'HEAD'], text=True).strip()
    config = project / 'expectrail.project.json'
    if not config.is_file():
        raise ValueError('project needs its own expectrail.project.json and approved contracts')
    # Identify all source/policy bytes, not just HEAD; detect changes during/resuming a batch.
    from harness import tree
    identity = tree.digest(project, skip=tree.GODOT_SKIP)
    plan = {'commit': commit, 'tree': identity, 'start': start, 'count': count,
            'ticks': ticks, 'viewport': viewport, 'project': str(project),
            'godotVersion': subprocess.check_output([str(godot), '--version'], text=True).strip(),
            'commandSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'offscreenSha256': hashlib.sha256(Path(__file__).with_name('offscreen.py').read_bytes()).hexdigest(),
            'producerSha256': hashlib.sha256(Path(__file__).with_name('producer.py').read_bytes()).hexdigest()}
    if (out / 'plan.json').exists() and json.loads((out / 'plan.json').read_text()) != plan:
        raise ValueError('existing plan differs; use a new output directory')
    write_json(out / 'plan.json', plan)
    env = environment(out, godot)
    # Discovery uses the same restricted environment as ingestion; restore caller environment.
    before = dict(os.environ)
    paths = []
    try:
        os.environ.clear(); os.environ.update(env)
        for seed in range(start, start + count):
            dest = out / 'seeds' / str(seed)
            if not (dest / 'summary.json').exists():
                if dest.exists():
                    raise ValueError(f'incomplete replay retained at {dest}')
                play(project, commit, seed, dest, ticks=ticks, godot=godot, viewport=viewport)
                if compact_replays:
                    compact(dest / 'replay')
                    shutil.rmtree(dest / 'replay/work')
            paths.extend(sorted((dest / 'reports').glob('*.json')))
            if (seed - start + 1) % 20 == 0:
                print(f'{project.name}: seeds {seed-start+1}/{count}, reports {len(paths)}', flush=True)
    finally:
        os.environ.clear(); os.environ.update(before)
    if tree.digest(project, skip=tree.GODOT_SKIP) != identity:
        raise ValueError('project changed during discovery')
    paths.extend(Path(p).resolve() for p in extra_reports)
    from expectrail.orchestrator.playtest import load
    documents = [load(path) for path in paths]
    if len({d['id'] for d in documents}) != len(documents):
        raise ValueError('duplicate report IDs; raw inputs are retained, no jobs silently skipped')
    if ingest_jobs < 1:
        raise ValueError('ingest_jobs must be positive')
    def submit(path):
        if tree.digest(project, skip=tree.GODOT_SKIP) != identity:
            raise ValueError('project changed during intake')
        with ingest_semaphore if ingest_semaphore is not None else nullcontext():
            return ingest(path, project, out / 'intakes', godot, timeout=timeout,
                          compact_replays=compact_replays)
    results = []
    with ThreadPoolExecutor(max_workers=ingest_jobs) as pool:
        for index, result in enumerate(pool.map(submit, paths)):
            results.append(result)
            print(f'{project.name}: intake {index+1}/{len(paths)} {result["outcome"]}', flush=True)
    grouped = groups(documents)
    result = {'reports': len(documents), 'groups': grouped, 'groupedCount': len(grouped),
              'outcomes': dict(Counter(r['outcome'] for r in results)), 'results': results}
    write_json(out / 'results.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--godot', required=True, type=Path)
    parser.add_argument('--start', type=int, default=10000)
    parser.add_argument('--count', type=int, default=200)
    parser.add_argument('--ticks', type=int, default=1200)
    parser.add_argument('--viewport', nargs=2, type=int)
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--ingest-jobs', type=int, default=1)
    parser.add_argument('--extra-report', action='append', default=[], type=Path)
    parser.add_argument('--compact-replays', action='store_true', help='after completion hash/remove rendered PNGs; gzip traces')
    args = vars(parser.parse_args(argv))
    args['extra_reports'] = args.pop('extra_report')
    result = batch(**args)
    return 1 if any(r['outcome'] in ('job-error', 'unclassified') for r in result['results']) else 0


if __name__ == '__main__':
    sys.exit(main())
