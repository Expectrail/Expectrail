"""STAND-IN ONLY: calibrate/judge/record/replay from engine boxes, never vision evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from agents.observations import _frame_box, _frame_tick, _view_at, engine_refs_by_frame
from agents.sam_observations import png_size, sam_usage
from expectrail import anchored, recorded
from tools import outside_trial, outside_vision
from tools.outside_vision_plan import key_digest, question

LABEL = 'STAND-IN ENGINE BOXES; NOT VISION EVIDENCE; NO MODEL CALLS OR SPEND'


class EngineBoxes:
    """Tautological positive control: answers are the engine observer's boxes, not image inference."""
    model = 'ENGINE-BOX-STAND-IN-NOT-VISION'
    provider = 'stand-in-engine-boxes-not-vision-evidence'
    base = 'stand-in'

    def __init__(self, *, clip=False):
        self.calls = 0
        self.keys = []
        self.traces = {}
        self.clip = clip

    def _ask(self, kind, png, prompts):
        png = Path(png)
        path = png.parent.parent/'trace.json'
        if path not in self.traces:
            self.traces[path] = json.loads(path.read_bytes())
        trace = self.traces[path]
        n = int(png.stem[1:])
        size = png_size(png)
        self.calls += 1
        self.keys.append(key_digest(question(kind,png,prompts)))
        if self.clip:
            tick = _frame_tick(n,max(trace['physicsTicksPerSecond']//60,1))
            row = trace['rows'][tick]
            body = row.get('body')
            box = _frame_box(_view_at(trace['rows'],tick),body) if body else None
            if box:
                box = [max(0,box[0]),max(0,box[1]),min(size[0],box[2]),min(size[1],box[3])]
                if box[0]>=box[2] or box[1]>=box[3]:
                    box = None
        else:
            boxes = engine_refs_by_frame(trace,size,[n]).get(n,{}).get('player',[])
            box = boxes[0] if boxes else None
        return [dict(box=box,score=1.0) if box else None for _ in prompts]

    def segment_at(self,png,points):
        return self._ask('point',png,points)

    def segment_in(self,png,boxes):
        return self._ask('box',png,boxes)


def mark(folder):
    for path in Path(folder).rglob('*'):
        if path.is_file() and path.suffix in ('.md','.html'):
            label = ('<div><strong>'+LABEL+'</strong></div>\n') if path.suffix=='.html' else ('**'+LABEL+'**\n\n')
            path.write_text(label+path.read_text())


def dry_run(project,data,receipt,out,*,clip=False):
    if out.exists():
        raise ValueError('--out must be new; stand-in evidence is never overwritten')
    before = sam_usage()
    model = EngineBoxes(clip=clip)
    recorder = recorded.RecordingClient(model)
    print(LABEL,flush=True)
    first = outside_vision.judge(project,data,receipt,out/'stand-in',client=recorder)
    calibration = json.loads((out/'stand-in/calibration.json').read_bytes())
    anchored.check_calibration(calibration)
    recording = recorder.recording(sample=project['name'], recorded_at=datetime.now(timezone.utc).date().isoformat(),run='stand-in-local-engine-boxes')
    path = out/'stand-in-vision-recording.json'
    recorded.write_recording(path,recording)
    offline = recorded.RecordedClient(recorded.read_recording(path))
    second = outside_vision.judge(project,data,receipt,out/'recorded-stand-in',client=offline)
    decisions = lambda rows:{r['change'] or 'pinned':r['decision'] for r in rows}
    if decisions(first)!=decisions(second) or offline.not_recorded:
        raise ValueError('stand-in recording did not replay the same verdicts exactly')
    plan = json.loads((out/'stand-in/request-plan.json').read_bytes())
    if sorted(model.keys)!=plan['requestKeyDigests']:
        raise ValueError('stand-in calls disagree with the no-model request plan')
    if sam_usage()!=before:
        raise ValueError('stand-in path changed live model usage counters')
    for run in ('stand-in','recorded-stand-in'):
        mark(out/run)
    summary = dict(label=LABEL,standIn=True,visionEvidence=False,clippedCollisionStress=clip,
        project=project['name'],captureDigest=receipt,calibrationEnabled=calibration['enabled'],
        calibrationFrames=calibration['frames'],rules=calibration['rules'],rates=calibration['rates'],
        verdicts=decisions(first),recordedReplayVerdicts=decisions(second),recordingAnswers=len(recording['answers']),
        standInQuestions=model.calls,recordedQuestions=offline.calls,recordedAnswers=offline.answered,
        missingRecordedAnswers=offline.not_recorded,modelRequestsSent=0,actualSpendUsd=0,
        requestPlanMatchesActualStandIn=True,requestPlan=plan,
        limitations='Engine-derived boxes are not independent visual evidence. A positive control does not predict SAM answers. The clipped-body stress is also a stand-in, not a measured SAM false alarm.')
    (out/'STAND-IN-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (out/'STAND-IN-README.md').write_text('# '+LABEL+'\n\n'+summary['limitations']+'\n\n'
        +'Calibration and verdicts were replayed through the actual recording reader. No model was instantiated.\n')
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',choices=[p['name'] for p in outside_trial.load_list()],required=True)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--digest',required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--clip-to-frame',action='store_true',help='STAND-IN stress: clip the physical collision box to the PNG, instead of the engine observer convention')
    args=parser.parse_args(argv)
    project=next(p for p in outside_trial.load_list() if p['name']==args.project)
    summary=dry_run(project,args.data,args.digest,args.out,clip=args.clip_to_frame)
    print(json.dumps({k:summary[k] for k in ('label','calibrationEnabled','verdicts','recordingAnswers','standInQuestions','modelRequestsSent','actualSpendUsd')},indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
