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
            'replaySha256': sha(data), 'isolation': isolation, 'engine': replay['engine']}


def preflight(project, data, receipt, *, for_calibration=True):
    """Validate every arm, selected policy and usable coverage before a question can be sent."""
    from tools.outside_vision_plan import calibration_selection, visible
    from agents.sam_observations import frame_files, window
    from expectrail.anchored import RULES
    from harness.run import GODOT_VERSION

    if capture_id(project, data) != receipt:
        raise ValueError('capture digest differs from the capture job output')
    selected = trial.project_spec(project)
    with tempfile.TemporaryDirectory() as tmp:
        policy = Path(tmp)
        shutil.copytree(trial.REPO / project['routes'], policy / 'routes')
        (policy / 'specs').mkdir()
        shutil.copyfile(selected, policy / 'specs' / selected.name)
        checks = verify.read_checks(policy, 'specs', ['routes/*.json'])
        if checks.problems or checks.drafts or len(checks.specs) != 1:
            raise ValueError('selected outside policy is not one usable approved check: '
                             + '; '.join(checks.problems or ['draft or missing approved check']))
        spec = checks.specs[0]
    runs, engines = {}, set()
    for case in variants(project):
        tree = None
        for path in routes(project):
            run = saved_run(data / case / path.stem, path)
            if tree is not None and tree != run['tree']:
                raise ValueError(f'{case}: routes name different game trees')
            tree = run['tree']
            route = json.loads(path.read_bytes())
            expected = verify.window_frames({}, route['ticks'], run['trace'])
            if (expected is None or len(run['trace']['rows']) != route['ticks']
                    or [row['tick'] for row in run['trace']['rows']] != list(range(route['ticks']))
                    or sorted(frame_files(run['framesDir'])) != expected):
                raise ValueError(f'{case}/{path.stem}: incomplete route trace or captured frame window')
            if problem := verify.input_map_problem(run['trace']):
                raise ValueError(f'{case}/{path.stem}: {problem}; nothing was asked')
            engine = run['engine']
            normalized = (engine.get('version') or '').replace('-stable', '.stable')
            if engine.get('renderer') != 'opengl3' or not normalized.startswith(GODOT_VERSION.replace('-stable', '.stable')):
                raise ValueError('outside capture must use the pinned Godot version and CI OpenGL3 renderer')
            engines.add(tuple(engine.get(k) for k in ('name', 'version', 'renderer', 'device')))
            if for_calibration and spec.get('coverage', {}).get('whenPlayerVisible'):
                states = [visible(run, n) for n in window(expected, spec)]
                if any(state is None for state in states):
                    raise ValueError(f'{case}/{path.stem}: player visibility is unknown before vision')
                if sum(state is True for state in states) < spec['coverage'].get('minFrames', 2):
                    raise ValueError(f'{case}/{path.stem}: insufficient in-play coverage before vision')
            runs[case, path.name] = run
    if len(engines) != 1:
        raise ValueError('outside variants were captured under different rendering environments')
    first = runs['pinned', routes(project)[0].name]
    selected_frames, _excluded = calibration_selection(first, spec)
    if for_calibration and spec.get('coverage', {}).get('whenPlayerVisible') and len(selected_frames) < RULES['minFrames']:
        raise ValueError('fewer than eight visible, unclipped calibration frames; nothing was asked')
    return selected, spec, runs


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


def calibration_markdown(doc):
    rates = doc['rates']
    state = 'used' if doc['enabled'] else 'not used: ' + '; '.join(doc['why'])
    return (f"\n**Anchored vision for {doc['game']['name']}** (#330): {state}. Measured on the clean run: "
            f"found at its place in {doc['frames']['found']} of {doc['frames']['asked']} asked frames "
            f"({rates['found']:.0%}); drawn size matches the collision box in {rates['size']:.0%}; "
            f"same answer from a point nudged inside the player in {rates['stable']:.0%}.\n")


def anchored(project, data, client, out, *, vision_every=1, spec=None, run=None):
    """The visual observer for this game: calibrated on the unchanged game's first route (#330), and
    used only when the calibration says so. Writes calibration.json and calibration.md to ``out``."""
    from expectrail import anchored as an, recorded

    first = routes(project)[0]
    run = run or saved_run(data / 'pinned' / first.stem, first)
    spec = spec or json.loads(trial.project_spec(project).read_bytes())
    from tools.outside_vision_plan import calibration_run
    game = {'name': project['name'], 'commit': project['commit']}
    try:
        with calibration_run(run, spec) as (scoped, every, selected, excluded):
            doc = an.calibrate(game, scoped, client, every=every)
    except verify.NoAnswer as exc:
        doc = an.judge_calibration(game, run['replaySha256'], [], an.RULES,
                                   model=str(getattr(client, 'model', 'unknown')),
                                   provider=str(getattr(client, 'provider', 'unknown')))
        doc['why'] = [(recorded.missing_reason(exc) or str(exc))[:200]] + doc['why'][:7]
    out.mkdir(parents=True, exist_ok=True)
    (out / 'calibration.json').write_text(json.dumps(doc, indent=1) + '\n')
    (out / 'calibration.md').write_text(calibration_markdown(doc))
    observer = an.AnchoredObserver(client, doc, every=vision_every)
    original = getattr(client, 'inner', client)
    return recorded.with_recorded_diagnostics(observer) if isinstance(original, recorded.RecordedClient) else observer


def judge(project, data, receipt, out, observer=None, client=None, *, vision_every=1):
    """Judge every variant. ``observer`` is used as given; with ``client`` instead, the anchored
    observer is calibrated on the unchanged game first (#330)."""
    if type(vision_every) is not int or vision_every < 1:
        raise ValueError('vision stride must be a positive integer')
    if observer is not None and vision_every != 1:
        raise ValueError('vision sampling requires the calibrated anchored observer')
    selected_spec, spec, validated = preflight(project, data, receipt, for_calibration=observer is None)
    if observer is None:
        from tools.outside_vision_plan import QuestionClient, plan, markdown_plan
        from expectrail.recorded import RecordedClient, RecordingClient
        conditional = spec.get('coverage', {}).get('whenPlayerVisible', False)
        if conditional:
            client = QuestionClient(client, conditional=True)
        elif not isinstance(client, RecordedClient):
            client = RecordingClient(client, reuse=True)
        request_plan = plan(project, spec, validated, every=vision_every)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'request-plan.json').write_text(json.dumps(request_plan, indent=2) + '\n')
        print(markdown_plan(request_plan), flush=True)
        observer = anchored(project, data, client, out, vision_every=vision_every, spec=spec, run=validated['pinned', routes(project)[0].name])
        # This existing artifact is already uploaded by the outside-vision workflow.
        with (out / 'calibration.md').open('a') as handle:
            handle.write(markdown_plan(request_plan) + '\n')
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
            shutil.copyfile(selected_spec, arm / 'specs' / selected_spec.name)
            game = arm / 'project'
            for path in routes(project):
                run = validated[case, path.name]
                if trees.setdefault(game, run['tree']) != run['tree']:
                    raise ValueError(f'{case}: routes name different game trees')
                runs[game, sha(path.read_bytes())] = run

        saved = verify.SavedReplays(trees, runs)
        for case, change in cases.items():
            start = time.monotonic()
            doc = verify.run_gate(repo=policy / case, base=policy / 'pinned' if change else None,
                                  game='project', routes=['routes/*.json'], specs='specs', out=out / case,
                                  work=policy / 'work' / case, replay=saved, rule=record.BOTH,
                                  require_sandbox=True, visual=observer, expectrail_commit=os.getenv('GITHUB_SHA'),
                                  vision_every=vision_every)
            decision = doc['decision']
            rows.append({'name': project['name'], 'commit': project['commit'], 'licence': project['licence'],
                         'change': change['name'] if change else None,
                         'what': change and change['what'], 'expect': change and change['expect'],
                         'exit': next(code for code, name in trial.VERDICTS.items() if name == decision),
                         'decision': decision, 'verdict': decision, 'seconds': round(time.monotonic() - start, 1),
                         'visionEvery': vision_every,
                         'checks': doc['counts'], 'reasons': doc['reasons'],
                         'failures': [f['reason'] for f in doc['findings']]})
            (out / 'outside-trial.md').write_text(trial.markdown(rows) + sampling_markdown(vision_every))
    return rows


def sampling_markdown(every):
    return (f"\n**Vision sampling:** requested every {every} frame(s) from the check window's first, plus its last. "
            "Each check uses the shared sampling plan: fractional visibility checks need every frame. "
            "The engine still checks every frame; calibration and the paired comparison keep their own stride 10. "
            f"A visual defect shorter than {every} frames may be missed. A sampled non-pass is refined "
            "on every remaining frame or needs review; a reaches witness can pass from samples. "
            "Missing-player rejection requires 3 consecutive negative observations in the refined sequence. "
            "Explicit spec coverage obligations are not relaxed. Default: 1.\n")


def positive_stride(value):
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('vision stride must be a positive integer') from exc
    if result < 1:
        raise argparse.ArgumentTypeError('vision stride must be a positive integer')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('capture', 'judge'):
        sub = commands.add_parser(name)
        sub.add_argument('--project', required=True, choices=[p['name'] for p in trial.load_list()])
        sub.add_argument('--out', type=Path, required=True)
        if name == 'judge':
            sub.add_argument('--vision-every', type=positive_stride, default=1,
                             help='opt-in anchored vision stride (default 1); shorter defects may be missed')
            sub.add_argument('--data', type=Path, required=True)
            sub.add_argument('--digest', required=True)
            sub.add_argument('--recording', type=Path,
                             help='answer from this vision recording only (no key, no spend); default: the live model, recorded')
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
    from expectrail import recorded

    if args.recording is not None:
        # Option A (#330): the answers recorded once by a person-dispatched live run, replayed for free.
        # A frame or question not in the recording gets no answer, so the verdict is needs-review.
        client = recorded.RecordedClient(recorded.read_recording(args.recording))
        args.out.mkdir(parents=True)
        judge(project, args.data, args.digest, args.out, client=client, vision_every=args.vision_every)
        print(f'Answered from the recording: {client.answered} of {client.calls} questions')
        return 0
    cap = os.getenv(CAP_ENV, '')
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?', cap) or not 0 < float(cap) <= 2:
        parser.error(f'{CAP_ENV} must be a positive amount of at most 2 dollars')
    if not os.getenv('MODEL_API_KEY', '').strip():
        parser.error('MODEL_API_KEY is missing')
    args.out.mkdir(parents=True)
    before = sam_usage()
    client = recorded.RecordingClient(MetaSamClient())
    try:
        judge(project, args.data, args.digest, args.out, client=client, vision_every=args.vision_every)
    finally:
        used = {key: value - before[key] for key, value in sam_usage().items()}
        (args.out / 'spend.json').write_text(json.dumps(used, indent=2) + '\n')
        print(f"Spend at list price: ${used['reservedUsd']:.4f}, {used['requests']} requests, "
              f"{used['images']} images answered")
        try:
            run = os.getenv('GITHUB_RUN_ID') or 'local'
            doc = client.recording(sample=project['name'], recorded_at=time.strftime('%Y-%m-%d', time.gmtime()),
                                   run=run)
            recorded.write_recording(args.out / 'vision-recording.json', doc)
        except recorded.RecordingError as exc:
            print(f'No recording was written: {exc}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
