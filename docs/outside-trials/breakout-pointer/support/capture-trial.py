from pathlib import Path
import json,os,subprocess,shutil
h=Path(__file__).parent;r=Path('/workspace/work/pointer-routes');scratch=Path('/dev/shm/expectrail-menu-trial-capture');scratch.mkdir(exist_ok=True)
for case in ('pinned-1','pinned-2','pinned-3','harmless','broken'):
 game=Path('/workspace/work/breakout-pointer-source') if case.startswith('pinned') else Path('/workspace/work/breakout-pointer-variants')/case
 out=scratch/'runs'/case
 cmd=['python3',str(h/'trial-command.py'),'--label','capture-'+case,'--tmpdir',str(scratch),'--timeout','300','--','python3','-m','harness.run','--game',str(game),'--route',str(game/'routes/pointer-auto.json'),'--out',str(out),'--sandbox','auto']
 subprocess.run(cmd,cwd=r,check=True)
 dest=h/'trial-evidence'/case;dest.mkdir(parents=True,exist_ok=True)
 for name in ('trace.json','replay.json','godot.log'):
  if (out/name).exists():shutil.copyfile(out/name,dest/name)
 frames=sorted((out/'frames').glob('*.png'))
 for n in (20,40,70,100):
  if n<len(frames):shutil.copyfile(frames[n],dest/f'frame-{n}.png')
 if not (out/'trace.json').exists():raise SystemExit('Replay failed; inspect '+str(dest))
 shutil.rmtree(out)
