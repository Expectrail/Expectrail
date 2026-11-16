"""Execute the preregistered #262 untuned measurement with frozen sensor/banks.

This module supplies routes, capture/byte checks and arithmetic only. It never
alters a sensor parameter or learns from evaluation pixels. Read the work-log plan.
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

from agents import template_observations as sensor
from agents import template_regions as regions
from agents import template_sensor_bench as bench
from expectrail.contracts import digest
from harness import run as harness

REPO = Path(__file__).resolve().parent.parent
ROUTES = REPO/'tests/fixtures/template-untuned/routes'
PLATFORM_CASES = {'clean': [], 'invisible': ['bugs/physics-fall-through/v1.patch','agents/fixtures/fix-but-hide-player.patch'],
                  'sinking': ['bugs/sinking/v2.patch'], 'broken': ['bugs/physics-fall-through/v1.patch']}
OUTSIDE_CASES = {'clean': [], 'invisible': ['tests/outside/kinematic-character/changes/invisible.patch'],
                 'broken': ['tests/outside/kinematic-character/changes/broken.patch']}


def selected_frames(hashes, excluded):
    return [n for n, value in enumerate(hashes) if value not in excluded]


def totals(statuses, selected, crossed=(), region_unknown=(), region_applicable=True):
    """Measured disagreement, unknowns and once-per-frame union; no missing-as-pass."""
    selected = set(selected)
    alarms = {n for n in selected if statuses[n] in ('not-found','displaced')}
    unknown = {n for n in selected if statuses[n] in ('unavailable','out-of-frame')}
    crossings = selected & set(crossed) if region_applicable else set()
    region_missing = selected & set(region_unknown) if region_applicable else set(selected)
    measured = len(selected)-len(unknown)
    union = alarms | crossings
    rate = len(union)/measured if measured else None
    return dict(frames=len(selected), measured=measured, presenceAlarms=len(alarms), crossings=len(crossings),
                alarms=len(union), falseAlarmRate=rate, unavailable=sum(statuses[n]=='unavailable' for n in selected),
                offscreen=sum(statuses[n]=='out-of-frame' for n in selected), regionUnavailable=len(region_missing),
                regionApplicable=region_applicable,
                complete=bool(selected) and not unknown and region_applicable and not region_missing,
                underTwoPercent=rate is not None and rate < .02,
                eligibleForLaterConsideration=bool(selected) and not unknown and region_applicable and not region_missing
                    and rate is not None and rate < .02)


def verify_freeze(root):
    freeze=json.loads((root/'frozen/freeze.json').read_text())
    for name,want in {**freeze['sensorFiles'],**freeze['routeFiles']}.items():
        if sensor.sha(REPO/name)!=want:raise ValueError(f'frozen source changed: {name}')
    if sensor.sha(root/'frozen/pre-measurement-plan.md')!=freeze['planSha256']:
        raise ValueError('original plan changed')
    if sensor.sha(root/'frozen/platformer-522-bank.json')!=freeze['platformerBankSha256']:
        raise ValueError('original platformer bank changed')
    own=json.loads((root/'frozen/kinematic-bank-status.json').read_text())
    if own['status']=='built' and sensor.sha(root/'frozen/kinematic-bank.json')!=own['rawSha256']:
        raise ValueError('outside bank changed')
    return freeze,own


def capture(root,name,route,game,patches,engine):
    target=root/'captures'/name
    if (target/'replay.json').exists():
        record=bench.checked_capture(target)
        expected=[sensor.sha(REPO/path) for path in patches]
        # The harness uses its own ordered patch digest; compare the actual source list
        # through a separate immutable capture identity rather than guessing its encoding.
        identity=json.loads((target/'measurement-inputs.json').read_text())
        wanted=dict(routeSha256=sensor.sha(route),sourceTree=harness.tree_digest(game),patches=expected)
        if identity!=wanted or record['route']['sha256']!=wanted['routeSha256']:
            raise ValueError('capture identity changed; refusing reuse')
        return target,record
    target.mkdir(parents=True,exist_ok=False)
    identity=dict(routeSha256=sensor.sha(route),sourceTree=harness.tree_digest(game),patches=[sensor.sha(REPO/p) for p in patches])
    print('CAPTURE evaluation',name,flush=True)
    record=harness.run(route,target,game=game,godot=engine,patches=[REPO/p for p in patches],capture_frames=True,sandbox='auto')
    bench.atomic_json(target/'measurement-inputs.json',identity)
    return target,record


def observe(root,arm,bank_path,capture_path,record,excluded,region_applicable):
    name=capture_path.name;out=root/'observations'/arm/name;out.mkdir(parents=True,exist_ok=True)
    bank=sensor.load_bank(bank_path)
    trace=json.loads((capture_path/'trace.json').read_text())
    timing=[];started=time.perf_counter()
    doc=sensor.from_replay(trace,replay_sha256=sensor.sha(capture_path/'replay.json'),frames_dir=capture_path/'frames',
        bank=bank,spec=bench.SPEC,fps=record['capture']['fps'],on_frame=lambda frame,seconds:timing.append(seconds))
    # Both readers validate the observations; all unknowns survive in the raw document.
    summary=sensor.summarize(doc)
    hashes=record['frameSha256'];selected=selected_frames(hashes,excluded)
    statuses={f['frame']:f['sensor']['player']['status'] for f in doc['frames']}
    applicable=region_applicable and bool(bank.get('groundReference'))
    full_region=regions.from_observations(doc,trace,bank.get('groundReference')) if applicable else None
    novel_region=None
    if applicable:
        proof=copy.deepcopy(full_region['proof']);keep=set(selected)
        for row in proof:
            if row['frame'] not in keep:row['box']=None
        novel_region=regions.check(proof,bank['groundReference'])
    full=totals(statuses,statuses,full_region['crossedFrames'] if full_region else (),
        full_region['unavailableFrames'] if full_region else (),applicable)
    novel=totals(statuses,selected,novel_region['crossedFrames'] if novel_region else (),
        novel_region['unavailableFrames'] if novel_region else (),applicable)
    result=dict(arm=arm,capture=name,bankSha256=digest(bank),bankRawSha256=sensor.sha(bank_path),
        replaySha256=sensor.sha(capture_path/'replay.json'),frameSha256=hashes,
        excludedFrames=sorted(set(statuses)-set(selected)),selectedFrames=selected,statuses=statuses,
        raw=full,novel=novel,summary=summary,region=full_region,novelRegion=novel_region,
        seconds=time.perf_counter()-started,maxFrameSeconds=max(timing) if timing else None,
        calibrationStatus=bank['calibration']['status'],threshold=bank['config']['matchThreshold'])
    bench.atomic_json(out/'template-observations.json',doc);bench.atomic_json(out/'result.json',result)
    print('MEASURED',arm,name,'raw',full,'novel',novel,flush=True)
    return result


def aggregate(rows,field):
    keys=('frames','measured','presenceAlarms','crossings','alarms','unavailable','offscreen','regionUnavailable')
    out={key:sum(row[field][key] for row in rows) for key in keys}
    out['falseAlarmRate']=out['alarms']/out['measured'] if out['measured'] else None
    out['complete']=bool(rows) and all(row[field]['complete'] for row in rows)
    out['underTwoPercent']=out['falseAlarmRate'] is not None and out['falseAlarmRate']<.02
    out['eligibleForLaterConsideration']=out['complete'] and out['underTwoPercent']
    return out


def seed_results(rows):
    output=[]
    for row in rows:
        if row['variant']=='clean':continue
        clean=next(r for r in rows if (r['arm'],r['source'],r['route'],r['variant'])==(row['arm'],row['source'],row['route'],'clean'))
        rule='pixel-absence/v1' if row['variant'] in ('invisible','sinking') else 'pixel-position-crosses-clean-region/v1'
        for field in ('raw','novel'):
            selected=set(range(len(row['frameSha256']))) if field=='raw' else set(row['selectedFrames'])
            selected_clean=set(range(len(clean['frameSha256']))) if field=='raw' else set(clean['selectedFrames'])
            if rule=='pixel-absence/v1':
                frames={int(n) for n,status in row['statuses'].items() if status in ('not-found','displaced')} & selected
            else:
                reg=row['region'] if field=='raw' else row['novelRegion']
                frames=set(reg['crossedFrames']) & selected if reg else set()
            clean_matches={int(n) for n,status in clean['statuses'].items() if status=='matched'} & selected_clean
            output.append(dict(arm=row['arm'],source=row['source'],route=row['route'],variant=row['variant'],selection=field,
                rule=rule,alarmFrames=sorted(frames),pairedWithMatchedClean=sorted(frames & clean_matches),
                detected=bool(frames & clean_matches),counts=row[field],
                supported=rule=='pixel-absence/v1' or row['region'] is not None))
    return output


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--outside',type=Path,required=True);p.add_argument('--godot',type=Path,required=True)
    args=p.parse_args(argv);root=args.root.resolve();freeze,own=verify_freeze(root)
    old=set(json.loads((root/'frozen/prior-frame-hashes.json').read_text()))
    own_excluded=set(old)
    for name in ('sensor-kinematic-cal-walk','sensor-kinematic-cal-air','sensor-kinematic-cal-turns','sensor-kinematic-cal-validation'):
        own_excluded.update(bench.checked_capture(root/'captures'/name)['frameSha256'])
    rows=[]
    sources=[('platformer',REPO/'game/platformer', [('coins',REPO/'harness/routes/coins.json'),('new',ROUTES/'sensor-untuned-platformer-v1.json')],PLATFORM_CASES),
             ('kinematic',args.outside,[('walk',REPO/'tests/outside/kinematic-character/routes/walk.json'),('new',ROUTES/'sensor-untuned-kinematic-v1.json')],OUTSIDE_CASES)]
    for source,game,routes,variants in sources:
        for route_name,route in routes:
            for variant,patches in variants.items():
                verify_freeze(root)
                path,record=capture(root,f'{source}-{route_name}-{variant}',route,game,patches,args.godot)
                arms=[('platformer-522',root/'frozen/platformer-522-bank.json',old,source=='platformer')]
                if source=='kinematic' and own['status']=='built':arms.append(('kinematic-calibrated',root/'frozen/kinematic-bank.json',own_excluded,True))
                for arm,bank,excluded,region in arms:
                    row=observe(root,arm,bank,path,record,excluded,region);row.update(source=source,route=route_name,variant=variant)
                    rows.append(row);verify_freeze(root)
                    bench.atomic_json(root/'measurement-partial.json',dict(rows=rows))
    groups=[]
    for source,arm in sorted({(r['source'],r['arm']) for r in rows}):
        clean=[r for r in rows if (r['source'],r['arm'],r['variant'])==(source,arm,'clean')]
        groups.append(dict(source=source,arm=arm,raw=aggregate(clean,'raw'),novel=aggregate(clean,'novel')))
    result=dict(evidence='Preregistered new public routes; frozen PR #522 sensor; no retuning',freeze=freeze,
        outsideBank=own,groups=groups,seeded=seed_results(rows),rows=rows)
    bench.atomic_json(root/'template-untuned-measurement.json',result)
    print('FINAL',json.dumps(groups),flush=True)
    return 0  # A measured over-target rate is a finding, never a task failure.


if __name__=='__main__':raise SystemExit(main())
