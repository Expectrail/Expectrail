"""Run the opt-in #330 loop offline. Never capture, dispatch, tune a bank, or create a live client.

python -m agents.calibrate_observer --observer template --bank BANK --selection RUN --clean RUN \
  --broken hidden=RUN=PATCH --broken behind-scenery=RUN=PATCH \
  --broken texture-blanked=RUN=PATCH --broken shifted-off-body=RUN=PATCH \
  --game GAME --texture player/robot.webp --out RECORD

Use --observer recorded-sam --recording RECORDING --candidate 'blue robot' ... for exact stored
SAM answers. An unanswered PNG/question remains unavailable; no nearest-image lookup exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from agents.calibration_observers import RecordedSam, Template, frames_from_run
from expectrail import calibration


def sampled(folder, every):
    replay = json.loads((Path(folder)/'replay.json').read_text())
    count = replay['capture']['frames']
    return frames_from_run(folder, sorted(set(range(0,count,every)) | ({count-1} if count else set())))


def report(doc):
    selected = doc['selected']
    floor = next((c['floor'] for c in doc['candidates'] if c['prompt']==selected), 1)
    def counts(rows, floor):
        states = [calibration.status(row,floor) for row in rows]
        return {s:states.count(s) for s in ('pass','fail','unavailable')}
    return dict(evidence=doc['observer']['evidence'], selected=selected, enabled=doc['enabled'],
                candidates=[dict(prompt=c['prompt'],floor=c['floor'],**counts(c['rows'],c['floor'])) for c in doc['candidates']],
                clean=counts(doc['clean'],floor),
                broken=[dict(name=v['name'],**counts(v['rows'],floor)) for v in doc['broken']],
                missed=doc['missed'],why=doc['why'])


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--observer',choices=['recorded-sam','template'],required=True)
    p.add_argument('--bank',type=Path);p.add_argument('--recording',type=Path)
    p.add_argument('--candidate',action='append')
    p.add_argument('--selection',type=Path,required=True);p.add_argument('--clean',type=Path,required=True)
    p.add_argument('--broken',action='append',required=True,help='NAME=RUN_FOLDER=PATCH_FILE (four entries)')
    p.add_argument('--game',type=Path,required=True);p.add_argument('--texture',action='append',required=True)
    p.add_argument('--every',type=int,default=10);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(argv)
    if not 1 <= a.every <= 60:p.error('--every must be between 1 and 60')
    if a.observer=='template':
        if not a.bank or a.recording:p.error('template requires --bank only')
        adapter=Template(a.bank);candidates=a.candidate or adapter.propose(a.game,a.texture)
    else:
        if not a.recording or a.bank:p.error('recorded-sam requires --recording only')
        from expectrail.recorded import read_recording
        adapter=RecordedSam(read_recording(a.recording));candidates=a.candidate or adapter.propose(a.game,a.texture)
    selection=sampled(a.selection,a.every)
    used={hashlib.sha256(Path(f['png']).read_bytes()).hexdigest() for f in selection}
    excluded={}
    def proof(name,folder):
        rows=sampled(folder,a.every)
        kept=[f for f in rows if hashlib.sha256(Path(f['png']).read_bytes()).hexdigest() not in used]
        excluded[name]=len(rows)-len(kept)
        return kept
    clean=proof('clean',a.clean)
    broken=[]
    for entry in a.broken:
        parts=entry.split('=')
        if len(parts)!=3 or parts[0] not in calibration.BROKEN:p.error('--broken must be NAME=RUN_FOLDER=PATCH_FILE')
        name,folder,patch=parts
        broken.append(dict(name=name,patchSha256=hashlib.sha256(Path(patch).read_bytes()).hexdigest(),frames=proof(name,folder)))
    if sorted(v['name'] for v in broken)!=sorted(calibration.BROKEN):p.error('name all four broken copies once')
    doc=calibration.calibrate(adapter=adapter,candidates=candidates,selection=selection,clean=clean,
                              broken=broken,game=a.game,textures=a.texture)
    calibration.write(a.out,doc)
    print(json.dumps(dict(record=str(a.out),excludedSelectionPngs=excluded,**report(doc)),indent=2))
    # A disabled calibration is a reported measurement, not a command failure.
    return 0


if __name__=='__main__':
    raise SystemExit(main())
