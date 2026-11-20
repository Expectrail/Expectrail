from pathlib import Path
import json,shutil
r=Path('$REPO');game=Path('$WORK/breakout-pointer-source');out=r/'tests/outside/breakout-pointer';out.mkdir(exist_ok=True)
for folder in ('checks','routes'):(game/folder).mkdir(exist_ok=True);(out/folder).mkdir(exist_ok=True)
for p in (r/'tests/outside/breakout/checks').glob('*.json'):
 spec=json.loads(p.read_text());assert 'approval' not in spec
 if spec['id']=='breakout-paddle-bounds':
  spec['instruction']='Draft: after the engine-measured Start click (release tick 14), the paddle drawing must stay in the 360 by 640 play area while the pointer sweep drives it. Require reaching the left lane, so an unstarted menu is not useful containment evidence. Sean must review the route, window, checkpoint and art-derived box before approval.'
  spec['window']={'fromFrame':20,'toFrame':70};spec['coverage']['minFrames']=40
 else:
  spec['instruction']='Draft: after Start is clicked and released at tick 14, the downward-launched ball should be below y=300 during frames 40..50. Require the paddle-left-lane checkpoint to confirm the round was exercised. Review the source-derived timing assumption and generated route before approval.'
 for root in (game,out):(root/'checks'/p.name).write_text(json.dumps(spec,indent=2)+'\n')
config=json.loads((game/'expectrail.project.json').read_text());config['routes']=['routes/pointer-auto.json'];config['approvedContracts']=['checks/breakout-paddle-bounds.json','checks/breakout-ball-starts.json']
# approvedContracts is the existing config field for check paths; neither check has an approval.
for root in (game,out):(root/'expectrail.project.json').write_text(json.dumps(config,indent=2)+'\n')
shutil.copyfile(game/'routes/pointer-auto.json',out/'routes/pointer-auto.json')
print('Draft checks written before measuring variants; neither has an approval. Config draft remains true.')
print('Bounds window 20..70, minimum 40; ball window 40..50, minimum 11; both require left-lane checkpoint.')
print('Reuse exactly the prior harmless comment and broken paddle-at-x=8 patches from tests/outside/breakout/changes.')
