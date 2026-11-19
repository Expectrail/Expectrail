from pathlib import Path
import json,tempfile
from tools.outside_trial import load_list,TrialError
h=Path(__file__).parent
p={'name':'breakout','repository':'https://github.com/mike0697/Breakout.git','commit':'0ac7aed444ea593a023d9b666c211d7ab8acd51e','path':'.','licence':'MIT','kind':'independent-author Godot 4.4 mouse-controlled paddle/ball game; config-only pointer trial starts gameplay; checks remain drafts','routes':'tests/outside/breakout-pointer/routes'}
file=h/'registration-probe.json';file.write_text(json.dumps({'format':'expectrail.outside-projects/v0','projects':[p]},indent=2)+'\n')
try:load_list(file)
except TrialError as exc:print(type(exc).__name__+': '+str(exc));raise SystemExit(2)
print('accepted')
