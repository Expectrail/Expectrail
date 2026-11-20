"""Compare two repairs of the same public kinematic-character fault through the local app backend."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from expectrail import app, app_kinematic, observation_timeline, viewer
from expectrail.gate import record
from expectrail.orchestrator import runner
from expectrail.orchestrator.store import FINAL, JobStore
from harness import tree
from tools import outside_trial


def apply_patch(folder, patch):
    subprocess.run(['git', 'apply', str(patch)], cwd=folder, check=True,
                   env={**os.environ, 'GIT_CEILING_DIRECTORIES': str(folder.parent)})


def first_measurement(paths, view):
    frame = view['firstFrame']
    difference, _ = viewer._first_difference(view)
    first_over = min((point['frame'] for series in view['series'].values() if series
                      for point in series['points'] if point['state'] == 'over'), default=None)
    selected = next((n for n in (frame, difference, first_over) if n is not None), None)
    if selected is None:
        return None
    result = {'frame': selected, 'firstFindingFrame': frame, 'firstMeasuredDifference': difference,
              'firstOverLimit': first_over}
    for side, arm in [('before', 'base'), ('after', 'head')]:
        series = view['series'].get(side) or {}
        point = next((p for p in series.get('points', []) if p['frame'] == selected), None)
        trace_path = paths.work / 'gate' / arm / 'walk' / 'trace.json'
        result[side] = {'reading': point, 'quantity': series.get('label'), 'tick': None}
        if point is not None and trace_path.is_file():
            trace = record.read_json(trace_path, 64 * 1024 * 1024, 'public walk trace')
            if trace.get('captureTimeline'):
                result[side]['tick'] = observation_timeline.tick_for(trace, selected)
    return result


def compare(local_app, before, after, out):
    body = {'before': str(before), 'after': str(after), 'projectConfig': True, 'executionClass': 'isolated'}
    info = local_app.inspect({**body, 'side': 'before', 'folder': str(before)})
    if info['rendering']['status'] not in ('match', 'mismatch', 'unknown', 'unavailable'):
        raise ValueError('The Before project must use the public vision recording.')
    shown = local_app.create(body)
    job = shown['id']
    deadline = time.monotonic() + 600
    while shown['phase'] not in FINAL:
        if time.monotonic() >= deadline:
            raise TimeoutError('The local app worker did not finish in ten minutes.')
        time.sleep(0.5)
        shown = local_app.status(job)
    store = local_app.store
    status = store.status(job)
    findings = local_app.findings(job, status)
    row = {'job': job, 'intent': store.request(job).get('intent', 'none'),
           'phase': shown['phase'], 'decision': shown['decision'], 'screen': shown['screen'],
           'renderer': info['rendering']['message'], 'diagnostics': [{k: d[k] for k in ('stage', 'code')} for d in shown['diagnostics']],
           'isolation': None, 'checks': [], 'findings': [], 'anchor': None, 'measurements': []}
    if findings is not None:
        isolation = findings['isolation']
        if not isolation['required'] or isolation['sandboxed'] != isolation['replays']:
            raise ValueError('The recorded game execution did not meet the requested isolation.')
        row.update(isolation=isolation, checks=findings['checks'], findings=findings['findings'])
        anchor = findings.get('anchor')
        if anchor:
            row['anchor'] = {'status': anchor['status'], 'routes': [
                {k: v for k, v in route.items() if k != 'frames'} for route in anchor['routes']]}
        paths = store.paths(job)
        for view in viewer.read_views(paths.output / 'viewer'):
            row['measurements'].append({'spec': view['spec'], 'route': view['route'],
                                        'first': first_measurement(paths, view)})
        (out / f'{after.name}-evidence.html').write_bytes(local_app.viewer_file(job, [viewer.EXPORT_NAME]))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='existing clean clone at the registered upstream commit')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    project = next(p for p in outside_trial.load_list() if p['name'] == 'kinematic-character')
    source = args.source or outside_trial.fetch(project, args.out.parent / 'sources')
    if (outside_trial.git('rev-parse', 'HEAD', cwd=source) != project['commit'] or
            outside_trial.git('status', '--porcelain', '--ignored', '--untracked-files=all', '--', project['path'], cwd=source)):
        raise ValueError('Use a clean kinematic-character checkout at the published pin.')
    os.environ.pop('MODEL_API_KEY', None)
    os.environ.pop('EXPECTRAIL_SAM_USD_CAP', None)
    args.out.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='expectrail-repair-pair-') as tmp:
        root = Path(tmp)
        before, wrong, restored = (root / name for name in ('before', 'mask-2', 'restored'))
        app_kinematic.prepare(source / project['path'], restored)
        shutil.copytree(restored, before)
        changes = app_kinematic.ROUTE.parent.parent / 'changes'
        apply_patch(before, changes / 'broken.patch')
        shutil.copytree(before, wrong)
        apply_patch(wrong, Path(__file__).resolve().parent / 'repair-pair' / 'wrong-mask-repair.patch')
        folders = (before, wrong, restored)
        original = {f.name: tree.digest(f) for f in folders}
        if len(set(original.values())) != 3:
            raise ValueError('The three prepared project trees must be distinct.')
        local_app = app.App(JobStore(root / 'jobs'), runner.spawn)
        try:
            rows = {f.name: compare(local_app, before, f, args.out) for f in (wrong, restored)}
        finally:
            local_app.close()
        if original != {f.name: tree.digest(f) for f in folders}:
            raise ValueError('Verification changed an input folder.')
    result = {'upstream': project['commit'], 'sourceTrees': original, 'candidates': rows}
    (args.out / 'repair-pair.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('## Kinematic-character repair comparison through the configured app backend\n')
    print('Before has collision mask 0. The candidates select mask 2 or restore the original mask.')
    for name, row in rows.items():
        print(f'\n### {name}\n')
        print(f"{name}: {row['screen']}, decision={row['decision']}, intent={row['intent']}, checks={len(row['checks'])}, "
              f"sandboxed replays={(row['isolation'] or {}).get('sandboxed', 0)}")
        for check in row['checks']:
            for side, seen in check.get('observed', {}).items():
                print(f"- {check['spec']} / {check['route']} {side}: engine {seen['engine']}, vision {seen['visual']}")
        for m in row['measurements']:
            point = m['first']
            if point is not None:
                print(f"- {m['spec']} / {m['route']}: first finding frame {point['firstFindingFrame']}, "
                      f"first measured difference {point['firstMeasuredDifference']}, first over limit {point['firstOverLimit']}. "
                      f"At frame {point['frame']}:")
                for side in ('before', 'after'):
                    reading = point[side]['reading'] or {}
                    print(f"  - {side}: physics tick {point[side]['tick']}, {point[side]['quantity']} = {reading.get('value')}")
        for route in (row['anchor'] or {}).get('routes', []):
            print(f"- Separate paired anchor on {route['route']}: in {route['in']}, out {route['out']}, "
                  f"moved {route['moved']}, no base {route['noBase']}, no answer {route['noAnswer']}, "
                  f"not asked {route['notAsked']}.")
        for diagnostic in row['diagnostics']:
            print(f"- {diagnostic['stage']}: {diagnostic['code']}")
    return 0 if all(row['phase'] == 'completed' and row['checks'] and
                    row['isolation']['replays'] > 0 for row in rows.values()) else 3


if __name__ == '__main__':
    raise SystemExit(main())
