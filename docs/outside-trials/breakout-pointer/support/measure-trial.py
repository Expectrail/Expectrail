from pathlib import Path
import json,hashlib
from expectrail.gate.verify import observations,window_frames
from expectrail.evaluator import evaluate
h=Path(__file__).parent;r=Path('$REPO')
route=json.loads((r/'tests/outside/breakout-pointer/routes/pointer-auto.json').read_text())
rows=[]
for case in ('pinned-1','pinned-2','pinned-3','harmless','broken'):
 d=h/'trial-evidence'/case;t=json.loads((d/'trace.json').read_text());obs=observations(t,hashlib.sha256((d/'replay.json').read_bytes()).hexdigest())
 verdicts=[]
 for p in sorted((r/'tests/outside/breakout-pointer/checks').glob('*.json')):
  spec=json.loads(p.read_text());assert 'approval' not in spec
  v=evaluate(spec,obs,trace=t,route=route['name'],capture_fps=60,expected_frames=window_frames(spec,route['ticks'],t,60))
  (d/(p.stem+'-verdict.json')).write_text(json.dumps(v,indent=2)+'\n')
  verdicts.append({'id':spec['id'],'result':v['result'],'reason':v['reason'],'firstFrame':v['firstFrame'],'framesJudged':v['framesJudged'],'coverage':v['coverage']})
 (d/'observations.json').write_text(json.dumps(obs,separators=(',',':'))+'\n')
 pos={tuple(row['player']) for row in t['rows']}
 rows.append({'case':case,'traceSha256':hashlib.sha256((d/'trace.json').read_bytes()).hexdigest(),'ticks':len(t['rows']),'distinctPlayerPositions':len(pos),'draftEngineDiagnostics':verdicts})
result={'pin':'0ac7aed444ea593a023d9b666c211d7ab8acd51e','routeTicks':route['ticks'],'pinnedTracesByteIdentical':len({x['traceSha256'] for x in rows[:3]})==1,'harmlessTraceIdenticalToPinned':rows[0]['traceSha256']==rows[3]['traceSha256'],'cliDecision':{'pinned':'needs-review','harmless':'needs-review','broken':'needs-review'},'cliChecksRun':0,'rows':rows}
(h/'trial-results.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
