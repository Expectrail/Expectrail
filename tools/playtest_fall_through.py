"""Record #531 intake on real Godot, with all model/fixer boundaries blocked.

python3 -m tools.playtest_fall_through --out runs/playtest-proof --sandbox require
Use --sandbox off only for an explicitly unsandboxed local diagnostic.
The trusted worker selects the existing engine-only diagnostic observer rule;
there is no substituted replay, observation, evaluator or reproduction rule.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import html
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest import mock

from expectrail import cli, resources
from expectrail.gate import verify
from expectrail.orchestrator import engines, playtest, runner, store
from harness import run as harness, tree

ROOT = resources.ROOT
SPEC = 'player-stays-above-ground'
REPORT = ROOT / 'contracts/examples/playtest-report-fall-through.json'


def _json(path, doc):
    path.write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')


def _project(path, *, bug, route):
    tree.copy(ROOT / 'game/platformer', path, skip=tree.GODOT_SKIP)
    if bug:
        subprocess.run(['patch', '-p1', '--batch', '--forward', '-d', str(path), '-i',
                        str(ROOT / 'bugs/physics-fall-through/v1.patch')], check=True, capture_output=True)
    config = {'format': 'expectrail.project/v1', 'adapter': 'godot',
              'entryScene': 'res://game_singleplayer.tscn', 'viewport': [1600, 960],
              'physicsTicksPerSecond': 120, 'captureFps': 60,
              'inputActions': ['move_left', 'move_right', 'jump', 'shoot'],
              'bindings': {'player': {'node': 'Level/Player', 'texture': 'res://player/robot.webp'}},
              'routes': ['routes/wait.json'], 'approvedContracts': ['checks/ground.json']}
    (path / 'routes').mkdir(); (path / 'checks').mkdir()
    _json(path / 'routes/wait.json', route)
    # Existing approval is copied byte for byte. No approval is written or changed.
    shutil.copyfile(ROOT / 'agents/specs' / (SPEC + '.json'), path / 'checks/ground.json')
    _json(path / 'expectrail.project.json', config)
    subprocess.run(['git', 'init', '-q', str(path)], check=True)
    subprocess.run(['git', '-C', str(path), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(path), '-c', 'user.name=Expectrail',
                    '-c', 'user.email=local@example.invalid', 'commit', '-qm',
                    'Disposable public fall-through intake project'], check=True)
    return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()


def _capture(source, target):
    target.mkdir(parents=True)
    for name in ('trace.json', 'replay.json', 'godot.log'):
        shutil.copyfile(source / name, target / name)
    frames = sorted((source / 'frames').glob('*.png'))
    kept = [frames[n] for n in (0, 8, 16, 40) if n < len(frames)]
    (target / 'frames').mkdir()
    for frame in kept:
        shutil.copyfile(frame, target / 'frames' / frame.name)
    return ['frames/' + f.name for f in kept]


def record(out: Path, *, sandbox='require'):
    if sandbox not in ('require', 'off'):
        raise ValueError('choose require or off explicitly')
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('choose an empty evidence output folder')
    binary = harness.find_godot()
    version = subprocess.check_output([str(binary), '--version'], text=True).strip()
    source = playtest.load(REPORT)
    captures, results = [], []
    with tempfile.TemporaryDirectory(prefix='expectrail-playtest-real-') as tmp:
        tmp = Path(tmp)
        projects = {}
        for name, bug in (('bug', True), ('clean', False)):
            path = tmp / name
            commit = _project(path, bug=bug, route=source['route'])
            projects[name] = (path, commit)
        jobs = store.JobStore(tmp / 'jobs')
        active = {'case': None}

        def replay(route, game, folder, frames):
            # Use the shipped bundled-game collision/position observer, as sample does.
            # project=None selects that existing path, not configured drawing-role boxes.
            # No trace field, observation or check is replaced; the PNGs are real captures.
            run = verify.harness_replay(route, game, folder, frames, sandbox=sandbox,
                                        checkouts=(game,), adapter='godot', project=None)
            meta = json.loads((folder / 'replay.json').read_text())
            target = out / active['case'] / ('replay-' + str(len(captures) + 1))
            kept = _capture(folder, target)
            captures.append({'case': active['case'], 'path': target.relative_to(out).as_posix(),
                             'isolation': meta['isolation'], 'framesKept': kept,
                             'traceSha256': hashlib.sha256((target / 'trace.json').read_bytes()).hexdigest()})
            return run

        created = []
        def spawn(st, job):
            created.append(job)
            runner.work(st, job, {'godot': engine})

        # Guard both constructors and sending boundaries, even if another path is introduced.
        with contextlib.ExitStack() as guards:
            boundaries = {}
            for label, name in (
                    ('observerConstructors', 'expectrail.orchestrator.engines.FramesObserver.__init__'),
                    ('modelConstructors', 'agents.sam_observations.MetaSamClient'),
                    ('modelRequests', 'urllib.request.urlopen'),
                    ('proposerCalls', 'expectrail.orchestrator.reproduction.propose'),
                    ('fixerCalls', 'agents.fixer.run_fixer'),
                    ('fixerTransportConstructors', 'agents.gateway.muse_gateway')):
                boundaries[label] = guards.enter_context(mock.patch(name, side_effect=AssertionError(label + ' forbidden')))
            engine = engines.GodotGate(replay=replay, rule='engine-only', visual=None)
            guards.enter_context(mock.patch.object(runner, 'spawn', side_effect=spawn))
            for name, project_name in (('reproduced', 'bug'), ('not-reproduced', 'clean'), ('anchor-desync', 'bug')):
                active['case'] = name
                project, commit = projects[project_name]
                report = copy.deepcopy(source)
                report['target']['commit'] = commit
                if name == 'anchor-desync':
                    report['fault']['anchor']['x'] += report['fault']['anchor']['tolerancePx'] + 1
                case = out / name; case.mkdir(exist_ok=True)
                path = case / 'report.json'; playtest.write(path, report)
                log = io.StringIO()
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    code = cli.main(['ingest', str(path), '--project', str(project), '--jobs-root',
                                     str(jobs.root), '--json', '--timeout', '900'])
                (case / 'cli.log').write_text(log.getvalue())
                if not created:
                    raise RuntimeError('ingest did not create a job: ' + log.getvalue())
                status = jobs.status(created[-1])
                _json(case / 'status.json', status)
                paths = jobs.paths(status['id'])
                precheck = json.loads((paths.output / 'playtest-precheck.log').read_text())
                _json(case / 'precheck.json', precheck)
                for file in ('findings.json', 'playtest-reproduction.json'):
                    if (paths.output / file).exists():shutil.copyfile(paths.output / file, case / file)
                # Preserve sequence: anchor proof, then approved check outcomes, then kind, then calls.
                results.append({'case': name, 'anchorReached': [all(r['coverage']['reached']) for r in precheck],
                                'baseGroundCheck': [c['result'] for r in precheck for c in r.get('checks', []) if c['spec'] == SPEC],
                                'reproductionKind': status.get('reproduction', {}).get('kind'),
                                'reproductionLabel': 'approved check' if status.get('reproduction', {}).get('kind') == 'approved' else 'none',
                                'boundaries': {key: value.call_count for key, value in boundaries.items()},
                                'exit': code, 'decision': status['decision'], 'reasons': status['reasons']})
    doc = {'engine': version, 'observerRule': 'engine-only', 'grade': 'diagnostic',
           'engineObservation': 'existing bundled-game collision/position observer (project=None)',
           'sandboxRequested': sandbox, 'liveModelMeasured': False, 'cases': results, 'replays': captures,
           'frameSelection': 'Only frames 0, 8, 16 and 40 are retained per replay; manifests describe the full original capture.'}
    _json(out / 'summary.json', doc)
    rows = ''.join('<tr><td>'+html.escape(r['case'])+'</td><td>'+html.escape(str(r['anchorReached']))+
                   '</td><td>'+html.escape(str(r['baseGroundCheck']))+'</td><td>'+html.escape(r['reproductionLabel'])+
                   '</td><td>'+html.escape(str(r['boundaries']))+'</td></tr>' for r in results)
    links = ''.join('<li><a href="'+html.escape(c['path'])+'/trace.json">'+html.escape(c['path'])+
                    ' trace</a> · <a href="'+html.escape(c['path'])+'/replay.json">manifest</a>'+''.join(
                    '<br><img width="400" alt="Real Godot capture" src="'+html.escape(c['path']+'/'+f)+'">' for f in c['framesKept'])+'</li>' for c in captures)
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Expectrail playtest reproduction</title>'
        '<h1>Real Godot: fall-through report intake</h1><p>Engine-only diagnostic; sandbox requested: '+html.escape(sandbox)+
        '. No live model, fixer, repair or visual-correctness claim. Selected frames only.</p>'
        '<p><a href="summary.json">Summary</a> · <a href="reproduced/report.json">Handwritten report</a> · '
        '<a href="reproduced/precheck.json">Three base checks</a></p><table border="1"><tr><th>Report</th><th>Anchor reached</th>'
        '<th>Approved ground check</th><th>Reproduction</th><th>Forbidden calls</th></tr>'+rows+'</table><ul>'+links+'</ul>')
    return doc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--sandbox', choices=('require', 'off'), default='require')
    args = parser.parse_args(argv)
    doc = record(args.out, sandbox=args.sandbox)
    print(json.dumps({k: doc[k] for k in ('engine','sandboxRequested','cases')}, indent=2))
    return 0


if __name__ == '__main__':raise SystemExit(main())
