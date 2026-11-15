"""Measure #262 on separate clean and seeded-bug replays. Needs Godot, display, Pillow and NumPy.

No model calls, downloads, approvals, or source-game edits. The harness copies the game and applies
public patches to the copies. Calibration is frozen before any candidate is replayed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from agents import template_observations as sensor
from harness import run as harness
from expectrail.contracts import digest

ROOT = Path(__file__).resolve().parent.parent
SPEC = {'format': 'expectrail.test-spec/v0', 'id': 'template-player-visible',
        'instruction': 'Measure whether the calibrated player crop is visible.',
        'objects': {'player': {'prompt': 'player'}}, 'assertion': {'type': 'visible', 'object': 'player', 'minFraction': 1.0}}
CASES = [('clean-smoke', 'smoke', []), ('clean-combat', 'combat', []), ('clean-traversal', 'traversal', []),
         ('invisible-player', 'smoke', ['bugs/physics-fall-through/v1.patch', 'agents/fixtures/fix-but-hide-player.patch']),
         ('sinking', 'smoke', ['bugs/sinking/v2.patch']),
         ('fall-through', 'smoke', ['bugs/physics-fall-through/v1.patch'])]


def presence_alarm_frames(run):
    return {row['frame'] for row in run['summary']['disagreements'] if row['status'] in ('not-found', 'displaced')}


def run_alarm_frames(run):
    return presence_alarm_frames(run) | set(run.get('regionCheck', {}).get('crossedFrames', []))


def complete_clean(report):
    rows = [r for r in report['runs'] if r['name'].startswith('clean-')]
    return bool(rows) and all(r['summary']['measured'] == r['summary']['objectFrames'] > 0
        and not r['regionCheck']['unavailableFrames'] for r in rows)


def seed_detections(report):
    out = {}
    for name in ('invisible-player', 'sinking', 'fall-through'):
        rows = [r for r in report['runs'] if r['name'] == name]
        if len(rows) != 1:
            raise sensor.SensorError('measurement needs exactly one run for each seeded bug')
        row = rows[0]
        if name == 'fall-through':
            check = row['regionCheck']
            frames = check['crossedFrames']
            measured = len(check['proof']) > len(check['unavailableFrames'])
            rule = 'pixel-position-crosses-clean-region/v1'
        else:
            frames = sorted(presence_alarm_frames(row))
            measured = row['summary']['measured'] > 0
            rule = 'pixel-absence/v1'
        out[name] = dict(rule=rule, measured=measured, detected=bool(frames) and measured, frames=frames)
    return out


def check_report(report):
    """Read the measurement contract and verify its counts/rates before presenting them."""
    sensor.validate(report, 'template-measurement')
    for run in report['runs']:
        s, c = run['summary'], run['summary']['counts']
        measured = c['matched'] + c['not-found'] + c['displaced']
        alarms = c['not-found'] + c['displaced']
        if (s['measured'] != measured or s['objectFrames'] != sum(c.values())
                or len(s['disagreements']) != sum(c.values()) - c['matched']
                or s['agreementRate'] != (c['matched']/measured if measured else None)
                or s['alarmRate'] != (alarms/measured if measured else None)):
            raise sensor.SensorError('measurement counts and rates disagree')
        timing = run['timing']
        if (timing['frames'] != s['frames'] or timing['meanFrameSeconds'] != (
                timing['sensorSeconds']/timing['frames'] if timing['frames'] else None)
                or (timing['frames'] and not 0 <= timing['p95FrameSeconds'] <= timing['maxFrameSeconds'])):
            raise sensor.SensorError('measurement timing does not match its frame count')
    if report['format'] == 'expectrail.template-measurement/v1':
        from agents import template_regions
        for row in report['runs']:
            actual = template_regions.check(row['regionCheck']['proof'], report['groundReference'], tolerance=row['regionCheck']['tolerancePx'])
            if actual != row['regionCheck'] or [p['frame'] for p in actual['proof']] != list(range(row['summary']['frames'])):
                raise sensor.SensorError('region proof does not match its reported crossings or frame count')
        if report['seedDetections'] != seed_detections(report):
            raise sensor.SensorError('seed detection claims disagree with the pixel evidence')
        wanted = complete_clean(report) and report['clean']['falseAlarmRate'] is not None and report['clean']['falseAlarmRate'] < .02
        seeded = all(item['measured'] and item['detected'] for item in report['seedDetections'].values())
        if report['targets']['falseAlarmTargetMet'] != wanted or report['targets']['seedDetectionsMet'] != seeded:
            raise sensor.SensorError('foreground target claims disagree with their evidence')
    clean = [r['summary'] for r in report['runs'] if r['name'].startswith('clean-')]
    measured = sum(s['measured'] for s in clean)
    alarms = sum(s['counts']['not-found'] + s['counts']['displaced'] for s in clean)
    if report['format'] == 'expectrail.template-measurement/v1':
        alarms = sum(len(run_alarm_frames(r)) for r in report['runs'] if r['name'].startswith('clean-'))
    if report['clean'] != dict(measured=measured, alarms=alarms, falseAlarmRate=alarms/measured if measured else None):
        raise sensor.SensorError('clean aggregate does not match the measured runs')
    invisible = [r['summary'] for r in report['runs'] if r['name'] == 'invisible-player']
    if len(invisible) != 1 or report['invisiblePlayerAlarms'] != (
            invisible[0]['counts']['not-found'] + invisible[0]['counts']['displaced']):
        raise sensor.SensorError('invisible-player count does not match its run')
    clean_rows = [r for r in report['runs'] if r['name'].startswith('clean-')]
    accuracy = bool(clean_rows) and all(r['summary']['frames'] and r['summary']['counts']['matched']/r['summary']['frames'] >= .95 for r in clean_rows)
    speed = all(r['timing']['maxFrameSeconds'] is not None and r['timing']['maxFrameSeconds'] < .3 for r in report['runs'])
    if report['targets']['accuracyMet'] != accuracy or report['targets']['speedMet'] != speed:
        raise sensor.SensorError('target claims do not follow from the measured numbers')
    return report


def render(report):
    check_report(report)
    def rate(n):
        return 'not measured' if n is None else f'{100*n:.2f}%'
    lines = ['# Template sensor measurements', '',
             f"Evidence: {report['evidence']}. Algorithm: {report['config']['algorithm']}.",
             f"Frozen bank: `{report['bankSha256']}`. Clean tree: `{report['cleanTree']}`.",
             'Calibration frames are excluded from these counts; each listed case is a separate replay.', '',
             f"Bank: {report['templateCount']} templates; calibration status: {report['calibration']['status']}; "
             f"threshold {report['config']['matchThreshold']} (floor {report['calibration']['thresholdFloor']}).",
             '| Run | Measured object-frames | Matched | Not found | Displaced | Unavailable | Off screen | Agreement | Alarm rate | Mean s/frame | p95 | Max |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for run in report['runs']:
        s, c = run['summary'], run['summary']['counts']
        lines.append(f"| {run['name']} | {s['measured']} | {c['matched']} | {c['not-found']} | {c['displaced']} | "
                     f"{c['unavailable']} | {c['out-of-frame']} | {rate(s['agreementRate'])} | {rate(s['alarmRate'])} | "
                     f"{run['timing']['meanFrameSeconds']} | {run['timing']['p95FrameSeconds']} | {run['timing']['maxFrameSeconds']} |")
    clean = report['clean']
    lines += ['', f"Clean-route false-alarm rate: **{rate(clean['falseAlarmRate'])}** "
              f"({clean['alarms']} alarms / {clean['measured']} measured object-frames).",
              f"Invisible-player pixel alarms: **{report['invisiblePlayerAlarms']}**. "
              'Zero alarms does not demonstrate detection.', '',
              f"95% matched on every clean route: {'MET' if report['targets']['accuracyMet'] else 'NOT MET'}. "
              f"Every measured frame under 0.3 s: {'MET' if report['targets']['speedMet'] else 'NOT MET'}.",
              'Sensor timing includes PNG decoding and matching, excludes Godot capture, bank preparation and checkpoint writes. '
              'All per-frame timings survive resume. Accuracy target includes unavailable/off-screen frames in its denominator.', '',
              'An alarm on a clean run is counted as a false alarm; legitimate occlusion can contribute. '
              'Unavailable and off-screen predictions are excluded from rate denominators and shown above. '
              'Matched crops do not certify colour, semantic identity, all sprite pixels, or other projects. '
              'A collision box is a search hint, not independent visibility truth. No default verdict uses these numbers.', '']
    if report['format'] == 'expectrail.template-measurement/v1':
        lines += ['## Seeded detections', '',
                  '| Seed | Rule | Detected frames | Detected |',
                  '| --- | --- | ---: | --- |']
        for name, item in report['seedDetections'].items():
            lines.append(f"| {name} | {item['rule']} | {len(item['frames'])} | {item['detected']} |")
        lines += ['', 'The run table above reports pixel presence. The clean false-alarm total also includes '
                  'crossings of frozen clean ground regions. Fall-through is detected by observed player pixels '
                  'crossing that reference, with 20 px tolerance; a visible player below the floor is not absence.',
                  'Ground regions come from the pinned clean calibration trace, not candidate ground/body rows. '
                  'They do not prove current floor visibility, detect moved floors, or certify a player already below '
                  'terrain at the first frame. Missing player pixels, camera or reference leave region evidence unavailable.',
                  f"Under 2% clean false alarms with complete clean evidence: {report['targets']['falseAlarmTargetMet']}. "
                  f"All three seeded bugs detected: {report['targets']['seedDetectionsMet']}.", '']
    return '\n'.join(lines)


def calibration_routes():
    """Dedicated clean routes: idle, walk, jump/double-jump, and shooting in both directions."""
    def route(name,events,seed=262):
        return dict(format='expectrail.route/v0',name=name,ticks=720,seed=seed,
                    description='Clean template calibration only; never a measured route.',
                    events=[dict(tick=t,action=a,pressed=p) for t,a,p in sorted(events)])
    walk=[(100,'move_right',True),(280,'move_right',False),(280,'move_left',True),
          (460,'move_left',False),(500,'move_right',True),(640,'move_right',False)]
    air=[(10,'move_right',True),(300,'move_right',False),(330,'move_left',True),(570,'move_left',False)]
    for tick in (40,90,180,220,370,420):air.extend([(tick,'jump',True),(tick+10,'jump',False)])
    fire=[(10,'move_right',True),(210,'move_right',False),(230,'move_left',True),
          (420,'move_left',False),(450,'move_right',True),(630,'move_right',False)]
    for tick in (30,90,150,270,330,390,480,540,600):fire.extend([(tick,'shoot',True),(tick+6,'shoot',False)])
    validation=[(t+7,a,p) for t,a,p in air+[(30,'shoot',True),(36,'shoot',False),(380,'shoot',True),(386,'shoot',False)]]
    return [route('cal-walk',walk),route('cal-air',air),route('cal-fire',fire),route('cal-validation',validation,263)]


def atomic_json(path, document):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(document,indent=2)+'\n')
    temporary.replace(path)


def checked_capture(root):
    replay=json.loads((root/'replay.json').read_text())
    if sensor.sha(root/'trace.json') != replay['trace']['sha256']:
        raise sensor.SensorError('recorded replay trace changed; refusing resume')
    files=sensor.frame_files(root/'frames')
    if sorted(files)!=list(range(len(replay['frameSha256']))):
        raise sensor.SensorError('recorded replay frames are missing; refusing resume')
    if any(sensor.sha(files[n])!=sha for n,sha in enumerate(replay['frameSha256'])):
        raise sensor.SensorError('recorded replay pixels changed; refusing resume')
    return replay


def frozen_bank(out, progress, calibrate):
    """Save calibration once. Check its original bytes before reusing it."""
    path = out / 'templates.json'
    if progress['bankSha256'] is None:
        bank = calibrate()
        atomic_json(path, bank)
        progress['bankSha256'] = sensor.sha(path)
        atomic_json(out / 'progress.json', progress)
        print(f"calibration frozen: {len(bank['templates'])} templates, threshold {bank['config']['matchThreshold']}", flush=True)
    elif sensor.sha(path) != progress['bankSha256']:
        raise sensor.SensorError('frozen calibration changed; refusing resume')
    return path


def read_checkpoint(path, identity):
    """Return only frames and timings belonging to the same bank and replay."""
    if not path.exists():
        return dict(identity=identity, frames={}, seconds={})
    checkpoint = json.loads(path.read_bytes())
    if checkpoint['identity'] != identity:
        raise sensor.SensorError('frame checkpoint belongs to different evidence')
    if (set(checkpoint['frames']) != set(checkpoint['seconds']) or any(
            str(frame['frame']) != key or not math.isfinite(checkpoint['seconds'][key]) or checkpoint['seconds'][key] < 0
            for key, frame in checkpoint['frames'].items())):
        raise sensor.SensorError('invalid frame checkpoint identity or timing')
    return checkpoint


def measure(out, *, godot, game=None, run_replay=None, config=None, evidence='real engine', resume=False, foreground_art=None, foreground_catalogue=None):
    import os
    import time
    out,game=Path(out).resolve(),Path(game or ROOT/'game/platformer').resolve()
    if out==game or game in out.parents:
        raise sensor.SensorError('measurement output must be outside the source game')
    if out.exists() and not resume:
        raise sensor.SensorError('use a new output directory or --resume')
    out.mkdir(parents=True,exist_ok=True)
    runner=run_replay or harness.run
    clean_tree=harness.tree_digest(game)
    if foreground_art is not None:
        from agents import template_foreground as foreground
        defaults = foreground.DEFAULTS
    else:
        defaults = sensor.CALIBRATION_DEFAULTS
    settings=dict(defaults,**(config or {}))
    if settings['matchThreshold']<0.90:
        raise sensor.SensorError('the threshold floor cannot be lowered below 0.90')
    plans=calibration_routes()
    progress_path=out/'progress.json'
    if resume and not progress_path.exists():
        raise sensor.SensorError('no v2 progress manifest; old banks cannot be resumed with a new algorithm')
    import numpy as np
    import PIL
    plan=dict(format='expectrail.template-progress/v1',cleanTree=clean_tree,config=settings,
              calibrationRoutes=plans,cases=[dict(name=n,routeSha256=sensor.sha(ROOT/f'harness/routes/{r}.json'),
                  patches=[sensor.sha(ROOT/p) for p in patches]) for n,r,patches in CASES],
              runtime=dict(numpy=np.__version__,pillow=PIL.__version__,threadEnvironment={
                  name:os.environ[name] for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','BLIS_NUM_THREADS')
                  if name in os.environ}),evidence=evidence)
    if foreground_catalogue is not None:
        if foreground_art is None:
            raise sensor.SensorError('a foreground catalogue needs selected foreground art')
        from agents import template_art
        foreground_catalogue = template_art.read_catalogue(foreground_catalogue)
        plan['foregroundCatalogueSha256'] = digest(foreground_catalogue)
    if foreground_art is not None:
        from agents import template_art, template_regions
        plan['implementationSha256'] = digest({Path(module.__file__).name: sensor.sha(module.__file__) for module in (sensor, foreground, template_art, template_regions)})
        plan['foregroundArt'] = foreground.art_sources(game, foreground_art, clean_tree)
    if progress_path.exists():
        progress=json.loads(progress_path.read_text())
        if progress.get('plan')!=plan:
            raise sensor.SensorError('resume inputs/configuration changed; use a new output directory')
    else:
        progress=dict(plan=plan,captures={},bankSha256=None,completed=[])
        atomic_json(progress_path,progress)
    def capture(name,route,patches=()):
        target=out/name
        if name in progress['captures']:
            replay=checked_capture(target)
            if sensor.sha(target/'replay.json')!=progress['captures'][name]:
                raise sensor.SensorError('replay metadata changed; refusing resume')
            return target,replay
        runner(route,target,game=game,godot=godot,patches=list(patches),capture_frames=True)
        replay=checked_capture(target)
        progress['captures'][name]=sensor.sha(target/'replay.json')
        atomic_json(progress_path,progress)
        print(f'{name}: capture saved',flush=True)
        return target,replay
    calibration=[]
    for route in plans:
        path=out/'calibration-routes'/f"{route['name']}.json"
        atomic_json(path,route)
        target,_=capture(route['name'],path)
        calibration.append(target)
    def calibrate():
        if foreground_art is not None:
            return foreground.calibrate_routes(calibration[:-1], calibration[-1], clean_game=game,
                clean_tree=clean_tree, art=foreground_art, config=settings, catalogue=foreground_catalogue)
        return sensor.calibrate_routes(calibration[:-1], calibration[-1], clean_tree=clean_tree, config=settings)
    bank_path = frozen_bank(out, progress, calibrate)
    bank = sensor.load_bank(bank_path)
    report=dict(format='expectrail.template-measurement/v1' if foreground_art is not None else 'expectrail.template-measurement/v0',evidence=evidence,config=bank['config'],
                cleanTree=clean_tree,bankSha256=digest(bank),calibrationFrames=sorted({t['frame'] for t in bank['templates']}),
                calibration=bank['calibration'],templateCount=len(bank['templates']),runtime=plan['runtime'],runs=[])
    if foreground_art is not None:
        report['groundReference'] = bank.get('groundReference')
    for name,route,patches in CASES:
        target,replay=capture(name,ROOT/f'harness/routes/{route}.json',[ROOT/p for p in patches])
        checkpoint_path=target/'sensor-progress.json'
        identity=dict(bankSha256=digest(bank),replaySha256=sensor.sha(target/'replay.json'))
        checkpoint = read_checkpoint(checkpoint_path, identity)
        def saved(frame,seconds):
            key=str(frame['frame']);checkpoint['frames'][key]=frame;checkpoint['seconds'][key]=seconds
            atomic_json(checkpoint_path,checkpoint)
            if len(checkpoint['frames'])%30==0:
                print(f"{name}: {len(checkpoint['frames'])} frames saved",flush=True)
        start=time.perf_counter()
        doc=sensor.from_replay(json.loads((target/'trace.json').read_text()),replay_sha256=identity['replaySha256'],
            frames_dir=target/'frames',bank=bank,spec=SPEC,fps=replay['capture']['fps'],
            completed={int(n):f for n,f in checkpoint['frames'].items()},on_frame=saved)
        atomic_json(target/'template-observations.json',doc)
        samples=[checkpoint['seconds'][str(f['frame'])] for f in doc['frames']]
        timing=dict(frames=len(samples),sensorSeconds=sum(samples),meanFrameSeconds=sum(samples)/len(samples) if samples else None,
                    p95FrameSeconds=float(np.percentile(samples,95)) if samples else None,
                    maxFrameSeconds=max(samples) if samples else None)
        row=dict(name=name,route=route,patches=patches,replaySha256=identity['replaySha256'],summary=sensor.summarize(doc),timing=timing)
        report['runs'].append(row)
        if foreground_art is not None:
            from agents import template_regions
            row['regionCheck'] = template_regions.from_observations(doc, json.loads((target/'trace.json').read_text()), bank.get('groundReference'))
        atomic_json(target/'template-result.json',row)
        if name not in progress['completed']:progress['completed'].append(name)
        atomic_json(progress_path,progress)
        print(f"{name}: {row['summary']['counts']['matched']}/{len(samples)} matched; "
              f"mean {timing['meanFrameSeconds']} s/frame; invocation {time.perf_counter()-start:.2f}s",flush=True)
    clean_runs=[r for r in report['runs'] if r['name'].startswith('clean-')]
    measured=sum(r['summary']['measured'] for r in clean_runs)
    alarms=sum(r['summary']['counts']['not-found']+r['summary']['counts']['displaced'] for r in clean_runs)
    if foreground_art is not None:
        alarms = sum(len(run_alarm_frames(r)) for r in clean_runs)
    report['clean']=dict(measured=measured,alarms=alarms,falseAlarmRate=alarms/measured if measured else None)
    invisible=next(r['summary'] for r in report['runs'] if r['name']=='invisible-player')
    report['invisiblePlayerAlarms']=invisible['counts']['not-found']+invisible['counts']['displaced']
    report['targets']=dict(cleanMatchedFraction=0.95,maxFrameSeconds=0.3,
        accuracyMet=all(r['summary']['frames'] and r['summary']['counts']['matched']/r['summary']['frames']>=0.95 for r in clean_runs),
        speedMet=all(r['timing']['maxFrameSeconds'] is not None and r['timing']['maxFrameSeconds']<0.3 for r in report['runs']))
    if foreground_art is not None:
        report['seedDetections'] = seed_detections(report)
        report['targets'].update(maxCleanFalseAlarmRate=.02,
            falseAlarmTargetMet=complete_clean(report) and report['clean']['falseAlarmRate'] < .02,
            seedDetectionsMet=all(item['measured'] and item['detected'] for item in report['seedDetections'].values()))
    atomic_json(out/'template-measurement.json',report)
    (out/'template-measurement.md').write_text(render(report))
    return report


def reuse_captures(source, *, clean_tree):
    """Replay runner for measuring the exact same hashed PNGs with a new clean bank.

    Verify the source game, route, patches, trace and every PNG before copying.
    No engine, candidate learning, or reuse of old observations/checkpoints occurs.
    Calibration is still frozen before measured cases are read by measure().
    """
    import shutil
    source = Path(source).resolve()

    def recorded(route, out, *, patches, **_kwargs):
        old = source / Path(out).name
        replay = checked_capture(old)
        patch_sha = None if not patches else (sensor.sha(patches[0]) if len(patches) == 1 else
            hashlib.sha256(b''.join(sensor.sha(p).encode() for p in patches)).hexdigest())
        if (replay['game']['tree'] != clean_tree or replay['route']['sha256'] != sensor.sha(route)
                or replay['game']['patchSha256'] != patch_sha
                or bool(replay['game']['patch']) != bool(patches)):
            raise sensor.SensorError('recorded capture does not match the requested game, route or patches')
        out = Path(out)
        out.mkdir(parents=True, exist_ok=False)
        for name in ('replay.json', 'trace.json'):
            shutil.copyfile(old/name, out/name)
        # Copy rather than link: an interrupted or edited comparison cannot change its baseline.
        shutil.copytree(old/'frames', out/'frames')
    return recorded


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--godot', type=Path, required=True, help='existing local binary; nothing is downloaded')
    p.add_argument('--clean-game', type=Path, default=ROOT/'game/platformer', help='trusted approved clean checkout')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--reuse-captures', type=Path, help='re-measure verified saved PNGs; no engine calls')
    p.add_argument('--foreground-catalogue', type=Path, help='optional trusted clean sprite-grid/pose catalogue')
    p.add_argument('--foreground-art', action='append', metavar='OBJECT=RELATIVE_PATH', help='opt into approved RGBA foreground witnesses from the trusted clean game')
    p.add_argument('--resume', action='store_true', help='continue a frozen v2 calibration and frame checkpoints')
    args = p.parse_args(argv)
    if not args.godot.is_file():
        p.error('--godot must name an installed binary')
    try:
        runner = reuse_captures(args.reuse_captures, clean_tree=harness.tree_digest(args.clean_game)) if args.reuse_captures else None
        art = None
        if args.foreground_art:
            art = {}
            for assignment in args.foreground_art:
                name, separator, path = assignment.partition('=')
                if not separator or not name or not path or name in art:
                    raise sensor.SensorError('--foreground-art needs unique OBJECT=RELATIVE_PATH entries')
                art[name] = path
        report = measure(args.out, godot=args.godot.resolve(), game=args.clean_game,resume=args.resume,
                         run_replay=runner, foreground_art=art, foreground_catalogue=args.foreground_catalogue)
    except (sensor.SensorError, OSError, ValueError, KeyError) as exc:
        p.exit(2, f'measurement incomplete: {exc}\n')
    print(render(report))
    # This is a measurement tool, not a product accept. No samples or no demonstrated hidden-player
    # alarm is incomplete evidence. Clean false alarms are reported, never tuned away here.
    return 0 if (report['clean']['measured'] and report['invisiblePlayerAlarms']
                 and report['targets']['accuracyMet'] and report['targets']['speedMet']
                 and report['targets'].get('falseAlarmTargetMet', True)
                 and report['targets'].get('seedDetectionsMet', True)) else 2


if __name__ == '__main__':
    raise SystemExit(main())
