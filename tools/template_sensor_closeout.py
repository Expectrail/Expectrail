"""Audit frozen #262 observations and generate the closeout tables. No model, calibration or tuning.

python3 -m tools.template_sensor_closeout --evidence CAPTURE_DIRECTORY --out RESULT.json --markdown REPORT.md
The supplied plan/observations are immutable inputs. Full PNG, trace, bank and source hashes are checked.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import inspect
import json
from pathlib import Path

from expectrail.contracts import digest, strict_loads, validate_v1

FORMAT='expectrail.template-closeout/v1'
STATES=('matched','not-found','displaced','unavailable','out-of-frame')
CASES=('clean-a','clean-b','invisible-player','sinking','fall-through')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metrics(frames, *, novel=False, clean=False):
    rows=[f for f in frames if f['newPixel'] or not novel]
    counts={s:sum(f['status']==s for f in rows) for s in STATES}
    measured=sum(counts[s] for s in STATES[:3]);presence=[f['frame'] for f in rows if f['status'] in STATES[1:3]]
    crossed=[f['frame'] for f in rows if f['newCrossed' if novel else 'crossed']]
    alarms=sorted(set(presence)|set(crossed))
    if any(f['status'] not in STATES[:3] and f['frame'] in alarms for f in rows):
        raise ValueError('Unknown evidence cannot supply an alarm or pass.')
    return {'frames':len(rows),'measured':measured,'counts':counts,'presenceAlarmFrames':presence,'crossedFrames':crossed,
            'alarmFrames':alarms,'agreementRate':counts['matched']/measured if measured else None,
            'alarmRate':len(alarms)/measured if measured else None,
            'falseAlarmRate':len(alarms)/measured if clean and measured else None,
            'regionUnavailable':sum(f['regionUnknown'] for f in rows)}


def paired(clean, changed, *, novel=False, region=False):
    matched={f['frame'] for f in clean if f['status']=='matched' and (f['newPixel'] or not novel)}
    if region:
        matched-={f['frame'] for f in clean if f['newCrossed' if novel else 'crossed']}
    return [f['frame'] for f in changed if f['frame'] in matched and (f['newPixel'] or not novel)
            and (f['newCrossed' if novel else 'crossed'] if region else f['status'] in STATES[1:3])]


def summarize_runs(runs, proof):
    if [r['name'] for r in runs]!=list(CASES):raise ValueError('Expected the five pre-registered cases in order.')
    results=[]
    for run in runs:
        frames=run['frames'];ids=[f['frame'] for f in frames]
        if ids!=list(range(len(frames))) or not frames:raise ValueError('Frame evidence is missing, duplicated or reordered.')
        if any(f['status'] not in STATES for f in frames):raise ValueError('Unknown sensor status.')
        clean=run['name'].startswith('clean-');entry={'name':run['name'],'clean':clean}
        entry.update(raw=metrics(frames,clean=clean),newPixels=metrics(frames,novel=True,clean=clean))
        if not clean:
            region=run['name']=='fall-through'
            entry['pairedRaw']=paired(runs[0]['frames'],frames,region=region)
            entry['pairedNewPixels']=paired(runs[0]['frames'],frames,novel=True,region=region)
        else:entry.update(pairedRaw=[],pairedNewPixels=[])
        results.append(entry)
    pooled={}
    for field in ('raw','newPixels'):
        rows=[r[field] for r in results if r['clean']]
        measured=sum(r['measured'] for r in rows);matched=sum(r['counts']['matched'] for r in rows)
        alarm_count=sum(len(r['alarmFrames']) for r in rows)
        pooled[field]={'frames':sum(r['frames'] for r in rows),'measured':measured,'matched':matched,
                       'alarms':alarm_count,'agreementRate':matched/measured if measured else None,
                       'falseAlarmRate':alarm_count/measured if measured else None,
                       'unavailable':sum(r['counts']['unavailable'] for r in rows),
                       'outOfFrame':sum(r['counts']['out-of-frame'] for r in rows)}
    if proof['frames']!=len(runs[0]['frames']) or len(runs[0]['frames'])!=len(runs[2]['frames']):
        raise ValueError('Pixel-only proof has the wrong frame denominator.')
    invisible=results[2]
    pixel_only=(proof['identicalPredictions'] and proof['identicalEngineCueRows'] and
                proof['cleanCueSha256']==proof['hiddenCueSha256'] and bool(invisible['pairedNewPixels']))
    done={'cleanAgreementPublished':all(r['newPixels']['measured']>0 for r in results[:2]),
          'cleanFalseAlarmsPublished':all(r['newPixels']['falseAlarmRate'] is not None for r in results[:2]),
          'invisiblePlayerPixelsOnly':pixel_only}
    done['allMet']=all(done.values())
    return {'runs':results,'pooledClean':pooled,'doneWhen':done}


def analysis_sha256():
    source='\n'.join(inspect.getsource(fn).strip('\n') for fn in (metrics,paired,summarize_runs))
    return hashlib.sha256(source.encode()).hexdigest()


def validate_report(doc):
    validate_v1(doc,'template-closeout')
    if doc['summary']!=summarize_runs(doc['runs'],doc['pixelOnlyProof']):raise ValueError('Closeout figures do not match frame evidence.')
    for run in doc['runs']:
        if run['newPixelSelectionSha256']!=digest([f['frame'] for f in run['frames'] if f['newPixel']]):
            raise ValueError('New-pixel selection digest is stale.')
    return doc


def load_evidence(folder):
    """Recompute from complete immutable artifacts, including every recorded PNG digest."""
    from agents import template_observations as sensor,template_regions as regions,template_sensor_bench as bench
    folder=Path(folder).resolve();repo=Path(__file__).resolve().parents[1]
    read=lambda p:strict_loads((folder/p).read_text())
    plan=read('pre-measurement-plan.json');freeze=read('execution-freeze.json')
    if sha(folder/'pre-measurement-plan.json')!=freeze['planSha256']:raise ValueError('The pre-measurement plan changed.')
    if sha(folder/'bank.json')!=freeze['bankSha256']:raise ValueError('The frozen bank changed.')
    if sha(folder/'excluded-png-hashes.json')!=freeze['excludedSha256']:raise ValueError('The hash exclusions changed.')
    for name,want in freeze['sensorFiles'].items():
        if sha(repo/name)!=want:raise ValueError('The frozen sensor changed: '+name)
    execution=read('evaluation-start.json')
    if execution['analysisRulesSha256']!=analysis_sha256():raise ValueError('The pre-evaluation counting rules changed.')
    if execution['wrapperSha256']!=sha(folder/'measure.py'):raise ValueError('The evaluation wrapper changed.')
    if sha(folder/'prior-frame-hashes.json')!=plan['exclusions']['priorHashFileSha256']:raise ValueError('The historical hash corpus changed.')
    expected_excluded=set(read('prior-frame-hashes.json'))
    for route in plan['calibration']['routes']:
        calibration=bench.checked_capture(folder/'calibration'/route['name'])
        if calibration['game']['tree']!=plan['cleanTree'] or calibration['game']['patchSha256'] is not None:
            raise ValueError('Calibration was not the trusted unpatched clean game.')
        expected_excluded.update(calibration['frameSha256'])
    bank=sensor.load_bank(folder/'bank.json');excluded=set(read('excluded-png-hashes.json'));runs=[]
    if excluded!=expected_excluded:raise ValueError('Exclusions differ from historical and calibration hashes.')
    for case in plan['cases']:
        name=case['name'];base=folder/'captures'/name;record=bench.checked_capture(base)
        route=plan['evaluationRoutes'][case['route']]
        route_file=folder/'routes'/(route['name']+'.json')
        if record['route']['sha256']!=sha(route_file):raise ValueError('The capture route changed.')
        patch_hashes=[sha(repo/p) for p in case['patches']]
        expected_patch=(None if not patch_hashes else patch_hashes[0] if len(patch_hashes)==1
                        else hashlib.sha256(''.join(patch_hashes).encode()).hexdigest())
        if record['game']['tree']!=plan['cleanTree'] or record['game']['patchSha256']!=expected_patch:
            raise ValueError('The capture used a different game or ordered patches.')
        obs=read('observations/'+name+'/observations.json');sensor.summarize(obs)
        if obs['replay']['sha256']!=sha(base/'replay.json') or obs['model']['sensor']['bankSha256']!=digest(bank):
            raise ValueError('Observation provenance differs from its capture or bank.')
        trace=read('captures/'+('clean-a' if name=='invisible-player' else name)+'/trace.json')
        raw=regions.from_observations(obs,trace,bank.get('groundReference'))
        selection=[n for n,h in enumerate(record['frameSha256']) if h not in excluded]
        novel_proof=copy.deepcopy(raw['proof'])
        for item in novel_proof:
            if item['frame'] not in set(selection):item['box']=None
        novel=regions.check(novel_proof,bank.get('groundReference'))
        if raw!=read('observations/'+name+'/region-raw.json') or novel!=read('observations/'+name+'/region-new-pixels.json'):
            raise ValueError('The frozen-region proof changed.')
        frames=[{'frame':f['frame'],'pngSha256':record['frameSha256'][f['frame']],
                 'status':f['sensor']['player']['status'],'newPixel':f['frame'] in selection,
                 'crossed':f['frame'] in raw['crossedFrames'],'newCrossed':f['frame'] in novel['crossedFrames'],
                 'regionUnknown':f['frame'] in raw['unavailableFrames']} for f in obs['frames']]
        sources={p:sha(folder/p) for p in [f'captures/{name}/replay.json',f'captures/{name}/trace.json',
                  f'observations/{name}/observations.json',f'observations/{name}/region-raw.json',
                  f'observations/{name}/region-new-pixels.json']}
        runs.append({'name':name,'route':route['name'],'frames':frames,'sources':sources,
                     'newPixelSelectionSha256':digest(selection)})
    clean_trace=read('captures/clean-a/trace.json');hidden=read('captures/invisible-player/trace.json')
    projection=lambda trace:[{k:r.get(k) for k in ('tick','body','player','playerVisible','view')} for r in trace['rows']]
    proof=read('pixel-only-proof.json')
    if (proof['cleanCueSha256']!=digest(projection(clean_trace)) or proof['hiddenCueSha256']!=digest(projection(hidden))
            or proof['identicalPredictions']!=(sensor.player_predictions(clean_trace,range(120))==sensor.player_predictions(hidden,range(120)))
            or proof['identicalEngineCueRows']!=(projection(clean_trace)==projection(hidden))
            or proof['entireTraceRowsIdentical']!=(clean_trace['rows']==hidden['rows'])):
        raise ValueError('The pixel-only cue proof changed.')
    result={'format':FORMAT,'baseCommit':plan['base'],'planSha256':freeze['planSha256'],
            'bank':{'rawSha256':freeze['bankSha256'],'canonicalSha256':digest(bank),'algorithm':bank['config']['algorithm'],
                    'threshold':bank['config']['matchThreshold'],'templates':len(bank['templates']),
                    'calibrationStatus':bank['calibration']['status']},
            'sensorFiles':freeze['sensorFiles'],'runs':runs,'pixelOnlyProof':proof,
            'summary':summarize_runs(runs,proof),'scope':{'optIn':True,'modelCalls':0,'defaultVerdictChanged':False,
            'calibrationOrThresholdsChangedAfterFreeze':False,'newPixelRule':'Exclude historical and all calibration/validation PNG hashes; count adverse scores.'}}
    return validate_report(result)


def rate(n,d):return f'{n}/{d} ({100*n/d:.2f}%)' if d else f'{n}/0 (unavailable)'


def markdown(doc):
    validate_report(doc);s=doc['summary'];bank=doc['bank']
    lines=['# No-model sensor closeout measurement (#262)','',
     'Generated from the frozen run record. No model calls, detector changes or verdict-readiness claim.','',
     '[Machine record](measurements/template-closeout-result.json) · [Pre-measurement plan](measurements/template-closeout-plan.json).','',
     '| Clean route / selection | Agreement with engine search prediction | Clean false alarms | Unavailable / off-screen |',
     '| --- | ---: | ---: | ---: |']
    for row in s['runs'][:2]:
        for field in ('raw','newPixels'):
            c=row[field];lines.append(f"| {row['name']} / {field} | {rate(c['counts']['matched'],c['measured'])} | {rate(len(c['alarmFrames']),c['measured'])} | {c['counts']['unavailable']} / {c['counts']['out-of-frame']} |")
    for field,c in s['pooledClean'].items():lines.append(f"| **Pooled / {field}** | **{rate(c['matched'],c['measured'])}** | **{rate(c['alarms'],c['measured'])}** | {c['unavailable']} / {c['outOfFrame']} |")
    lines+=['','Agreement means a pixel match whose box overlaps the engine prediction under the existing IoU rule. '
      'False alarms are the once-per-frame union of absence/displacement and applicable frozen-floor crossings. '
      'Unknown/off-screen frames are separate, never passes. New pixels exclude historical and calibration hashes, '
      'without looking at their scores. Frames are correlated samples, not independent trials.','',
      '| Seeded build | Raw event frames / measured | New-pixel event frames / measured | Matched-clean paired events: raw / new | Unknown/off-screen: raw; new |',
      '| --- | ---: | ---: | ---: | --- |']
    for row in s['runs'][2:]:
        a,b=row['raw'],row['newPixels'];region=row['name']=='fall-through'
        key='crossedFrames' if region else 'presenceAlarmFrames'
        lines.append(f"| {row['name']} | {len(a[key])}/{a['measured']} | {len(b[key])}/{b['measured']} | {len(row['pairedRaw'])} / {len(row['pairedNewPixels'])} | {a['counts']['unavailable']}/{a['counts']['out-of-frame']}; {b['counts']['unavailable']}/{b['counts']['out-of-frame']} |")
    lines+=['','These are alarm/crossing frames, not independently labelled frame-level recall. '
      'Fall-through uses visible pixel boxes crossing the clean floor reference; an off-screen player is unknown.','',
      '## Pixel-only invisible-player proof','',
      f"The paired runs have identical search predictions: **{doc['pixelOnlyProof']['identicalPredictions']}**, "
      f"identical engine cue rows: **{doc['pixelOnlyProof']['identicalEngineCueRows']}**, and identical complete trace rows: "
      f"**{doc['pixelOnlyProof']['entireTraceRowsIdentical']}**. The hidden PNGs were judged with the **clean trace**, "
      'the same frozen bank and the same spec. Thus pixels supply the distinguishing absence evidence. '
      'The engine still supplies a bounded search hint; this is not unconstrained full-screen detection.','',
      '## Frozen provenance and limits','',f"Base `{doc['baseCommit']}`; plan SHA-256 `{doc['planSha256']}`.",
      f"Bank `{bank['canonicalSha256']}`, {bank['templates']} templates, algorithm `{bank['algorithm']}`, threshold {bank['threshold']:g}; calibration `{bank['calibrationStatus']}`.",
      'The machine record contains every frame status/PNG digest and the hashes/paths of its replay, trace, observations '
      'and region proof. The accompanying handover contains these source records and regeneration commands.','',
      'This small, pre-registered bundled-game sample does not replace the earlier untuned-route 2.35% false-alarm '
      'finding, prove cross-game transfer, or make the sensor eligible for a release verdict. The existing opt-in '
      'JIT wiring is unchanged. No hosted dispatch, live model call, approval, game-source edit or workflow edit ran.','',
      f"Done when evidence complete for this scoped diagnostic sensor: **{s['doneWhen']['allMet']}**.",'']
    return '\n'.join(lines)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--markdown',type=Path,required=True);a=p.parse_args(argv)
    doc=load_evidence(a.evidence);a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(doc,indent=2,allow_nan=False)+'\n');a.markdown.write_text(markdown(doc))
    print(json.dumps(doc['summary']['pooledClean'],indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
