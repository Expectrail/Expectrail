"""Reproduce the Breakout drafts from the pinned source and saved route, without an engine."""
import argparse,copy,hashlib,json,math,re,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('inputs',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
pin=subprocess.check_output(['git','rev-parse','HEAD'],cwd=a.source,text=True).strip()
if pin != '0ac7aed444ea593a023d9b666c211d7ab8acd51e':raise SystemExit('source must be the published Breakout pin')
subprocess.run(['git','diff','--exit-code','HEAD'],cwd=a.source,check=True)
def text(name):return (a.source/name).read_text()
def number(key,source):return float(re.search(re.escape(key)+r'\s*=\s*([\d.]+)',source)[1])
def vec(key,source):return [float(v) for v in re.search(re.escape(key)+r'\s*=\s*Vector2\(([^)]+)\)',source)[1].split(',')]
project=text('project.godot');game=text('game.tscn');paddle=text('scenes/paddle.tscn');walls=text('scenes/walls.tscn');ball=text('scenes/ball.tscn')
w,h=number('window/size/viewport_width',project),number('window/size/viewport_height',project)
paddle_position=vec('position',game.split('[node name="Paddle"',1)[1]);ball_position=vec('position',game.split('[node name="Ball"',1)[1])
collision_size=vec('size',paddle);radius=number('radius',ball)
side_size=vec('size',walls);left=vec('position',walls.split('[node name="CollisionShape2D"',1)[1])[0]+side_size[0]/2;right=vec('position',walls.split('[node name="CollisionShape2D2"',1)[1])[0]-side_size[0]/2
# The scene's side walls enclose the viewport, and the paddle script clamps its
# collision shape to those viewport edges. The drawing fits the collision width.
assert left<=0 and right>=w
art=[float(v) for v in re.search(r'region = Rect2\(([^)]+)\)',paddle)[1].split(',')]
assert art[2]<=collision_size[0]
route=json.loads((a.inputs/'routes/pointer-auto.json').read_text());events=route['events']
release=next(e['tick'] for e in events if e.get('pointer',{}).get('button')=='left' and not e['pointer']['pressed'])
checkpoints=[]
for tick in (20,70):
 x=next(e['pointer']['position'][0] for e in events if e['tick']==tick)
 checkpoints.append({'type':'position-at-tick','tick':tick,'object':'player','x':x,'y':paddle_position[1],'tolerancePx':collision_size[0]/2})
assert abs(checkpoints[0]['x']-checkpoints[1]['x'])>collision_size[0]
assert release<20
specs={p.stem:json.loads(p.read_text()) for p in (a.inputs/'checks').glob('*.json')}
spec=specs['breakout-paddle-bounds'];spec['assertion']['region']['box']=[0,0,w,h];spec['coverage']['minFrames']=51;spec['coverage']['reached']=checkpoints
spec['instruction']='Draft: after Start, the whole paddle drawing stays inside the project viewport during frames 20..70 and the bound paddle reaches both route-derived positions at ticks 20 and 70, within half its collision width. Frozen play cannot pass. Review the viewport, walls, drawing, click and movement obligations before approval.'
b=specs['breakout-ball-starts'];b['assertion']['boundary']['value']=ball_position[1]+radius;b['coverage']['reached']=copy.deepcopy(checkpoints)
b['instruction']='Draft: after Start, the whole ball drawing is below its initial centre plus its collision radius during frames 40..50, and the paddle reaches the two route-derived positions at ticks 20 and 70. This demonstrates this seeded launch, not the correctness of every bounce. Review before approval.'
a.output.mkdir(parents=True,exist_ok=True)
for name,spec in specs.items():
 assert 'approval' not in spec
 (a.output/(name+'.json')).write_text(json.dumps(spec,indent=2)+'\n')
inputs=['project.godot','game.tscn','scenes/paddle.tscn','scenes/walls.tscn','scenes/ball.tscn','scripts/paddle.gd','scripts/ball.gd']
doc={'pin':'0ac7aed444ea593a023d9b666c211d7ab8acd51e','sources':{name:{'sha256':hashlib.sha256((a.source/name).read_bytes()).hexdigest(),'url':'https://github.com/mike0697/Breakout/blob/0ac7aed444ea593a023d9b666c211d7ab8acd51e/'+name} for name in inputs},'viewport':[w,h],'wallInnerX':[left,right],'paddleCollisionSize':collision_size,'paddleDrawingSize':art[2:],'paddleInitialPosition':paddle_position,'movementCheckpoints':checkpoints,'startReleaseTick':release,'ballInitialPosition':ball_position,'ballCollisionRadius':radius,'ballBoundaryY':ball_position[1]+radius,'windowRationale':'Paddle 20..70 lies after click release 14 and within the first sweep; ball 40..50 tests the seeded initial downward launch. Windows are authored policy, not inferred engine facts.'}
(a.output/'derivation.json').write_text(json.dumps(doc,indent=2)+'\n');print(json.dumps(doc,indent=2))
