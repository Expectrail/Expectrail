from pathlib import Path
import json,shutil
r=Path('/workspace/work/pointer-routes');game=Path('/workspace/work/breakout-pointer-source');h=Path(__file__).parent
pending=json.loads((game/'expectrail.project.draft.json').read_text());c=pending['config']
c['bindings']={'player':{'node':'Paddle','texture':'res://break assets/paddle/sp_paddle_long_strip2.png'},'ball':{'node':'Ball','texture':'res://break assets/Misc/sp_ball.png'}}
(game/'expectrail.project.json').write_text(json.dumps(c,indent=2)+'\n')
(h/'init-generated').mkdir(exist_ok=True)
shutil.copyfile(game/'expectrail.project.draft.json',h/'init-generated/expectrail.project.draft.json')
shutil.copyfile(game/c['routes'][0],h/'init-generated/route.json')
print('Completed the draft config, selecting Paddle as player and Ball as ball, with their own art. draft remains true. No approval added.')
print('Generated route:',c['routes'][0]);print(json.loads((game/c['routes'][0]).read_text())['description'])
