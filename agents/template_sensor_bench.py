"""Measure #262 on separate clean and seeded-bug replays. Needs Godot, display, Pillow and NumPy.

No model calls, downloads, approvals, or source-game edits. The harness copies the game and applies
public patches to the copies. Calibration is frozen before any candidate is replayed.
"""
from __future__ import annotations

import argparse
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
    clean = [r['summary'] for r in report['runs'] if r['name'].startswith('clean-')]
    measured = sum(s['measured'] for s in clean)
    alarms = sum(s['counts']['not-found'] + s['counts']['displaced'] for s in clean)
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


def measure(out, *, godot, game=None, run_replay=None, config=None, evidence='real engine', resume=False):
    import os
    import time
    import numpy as np
    import PIL
    out,game=Path(out).resolve(),Path(game or ROOT/'game/platformer').resolve()
    if out==game or game in out.parents:
        raise sensor.SensorError('measurement output must be outside the source game')
    if out.exists() and not resume:
        raise sensor.SensorError('use a new output directory or --resume')
    out.mkdir(parents=True,exist_ok=True)
    runner=run_replay or harness.run
    clean_tree=harness.tree_digest(game)
    settings=dict(sensor.DEFAULTS,**(config or {}))
    if settings['matchThreshold']<0.90:
        raise sensor.SensorError('the threshold floor cannot be lowered below 0.90')
    plans=calibration_routes()
    plan=dict(format='expectrail.template-progress/v1',cleanTree=clean_tree,config=settings,
              calibrationRoutes=plans,cases=[dict(name=n,routeSha256=sensor.sha(ROOT/f'harness/routes/{r}.json'),
                  patches=[sensor.sha(ROOT/p) for p in patches]) for n,r,patches in CASES],
              runtime=dict(numpy=np.__version__,pillow=PIL.__version__,threadEnvironment={
                  name:os.environ[name] for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','BLIS_NUM_THREADS')
                  if name in os.environ}),evidence=evidence)
    progress_path=out/'progress.json'
    if progress_path.exists():
        progress=json.loads(progress_path.read_text())
        if progress.get('plan')!=plan:
            raise sensor.SensorError('resume inputs/configuration changed; use a new output directory')
    elif resume:
        raise sensor.SensorError('no v2 progress manifest; old banks cannot be resumed with a new algorithm')
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
    bank_path=out/'templates.json'
    if progress['bankSha256'] is not None:
        bank=sensor.load_bank(bank_path)
        if sensor.sha(bank_path)!=progress['bankSha256']:
            raise sensor.SensorError('frozen calibration changed; refusing resume')
    else:
        bank=sensor.calibrate_routes(calibration[:-1],calibration[-1],clean_tree=clean_tree,config=settings)
        atomic_json(bank_path,bank)
        progress['bankSha256']=sensor.sha(bank_path)
        atomic_json(progress_path,progress)
        print(f"calibration frozen: {len(bank['templates'])} templates, threshold {bank['config']['matchThreshold']}",flush=True)
    report=dict(format='expectrail.template-measurement/v0',evidence=evidence,config=bank['config'],
                cleanTree=clean_tree,bankSha256=digest(bank),calibrationFrames=sorted({t['frame'] for t in bank['templates']}),
                calibration=bank['calibration'],templateCount=len(bank['templates']),runtime=plan['runtime'],runs=[])
    for name,route,patches in CASES:
        target,replay=capture(name,ROOT/f'harness/routes/{route}.json',[ROOT/p for p in patches])
        checkpoint_path=target/'sensor-progress.json'
        identity=dict(bankSha256=digest(bank),replaySha256=sensor.sha(target/'replay.json'))
        if checkpoint_path.exists():
            checkpoint=json.loads(checkpoint_path.read_text())
            if checkpoint['identity']!=identity:
                raise sensor.SensorError('frame checkpoint belongs to different evidence')
            if (set(checkpoint['frames']) != set(checkpoint['seconds']) or any(
                    str(frame['frame']) != key or not math.isfinite(checkpoint['seconds'][key]) or checkpoint['seconds'][key] < 0
                    for key,frame in checkpoint['frames'].items())):
                raise sensor.SensorError('invalid frame checkpoint identity or timing')
        else:
            checkpoint=dict(identity=identity,frames={},seconds={})
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
        atomic_json(target/'template-result.json',row)
        if name not in progress['completed']:progress['completed'].append(name)
        atomic_json(progress_path,progress)
        print(f"{name}: {row['summary']['counts']['matched']}/{len(samples)} matched; "
              f"mean {timing['meanFrameSeconds']} s/frame; invocation {time.perf_counter()-start:.2f}s",flush=True)
    clean_runs=[r for r in report['runs'] if r['name'].startswith('clean-')]
    measured=sum(r['summary']['measured'] for r in clean_runs)
    alarms=sum(r['summary']['counts']['not-found']+r['summary']['counts']['displaced'] for r in clean_runs)
    report['clean']=dict(measured=measured,alarms=alarms,falseAlarmRate=alarms/measured if measured else None)
    invisible=next(r['summary'] for r in report['runs'] if r['name']=='invisible-player')
    report['invisiblePlayerAlarms']=invisible['counts']['not-found']+invisible['counts']['displaced']
    report['targets']=dict(cleanMatchedFraction=0.95,maxFrameSeconds=0.3,
        accuracyMet=all(r['summary']['frames'] and r['summary']['counts']['matched']/r['summary']['frames']>=0.95 for r in clean_runs),
        speedMet=all(r['timing']['maxFrameSeconds'] is not None and r['timing']['maxFrameSeconds']<0.3 for r in report['runs']))
    atomic_json(out/'template-measurement.json',report)
    (out/'template-measurement.md').write_text(render(report))
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--godot', type=Path, required=True, help='existing local binary; nothing is downloaded')
    p.add_argument('--clean-game', type=Path, default=ROOT/'game/platformer', help='trusted approved clean checkout')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--resume', action='store_true', help='continue a frozen v2 calibration and frame checkpoints')
    args = p.parse_args(argv)
    if not args.godot.is_file():
        p.error('--godot must name an installed binary')
    try:
        report = measure(args.out, godot=args.godot.resolve(), game=args.clean_game,resume=args.resume)
    except (sensor.SensorError, OSError, ValueError, KeyError) as exc:
        p.exit(2, f'measurement incomplete: {exc}\n')
    print(render(report))
    # This is a measurement tool, not a product accept. No samples or no demonstrated hidden-player
    # alarm is incomplete evidence. Clean false alarms are reported, never tuned away here.
    return 0 if (report['clean']['measured'] and report['invisiblePlayerAlarms']
                 and report['targets']['accuracyMet'] and report['targets']['speedMet']) else 2


if __name__ == '__main__':
    raise SystemExit(main())
