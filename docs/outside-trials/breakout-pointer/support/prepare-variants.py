from pathlib import Path
import shutil,subprocess,os,hashlib
source=Path('$WORK/breakout-pointer-source');root=Path('$WORK/breakout-pointer-variants');root.mkdir(exist_ok=True)
for name in ('harmless','broken'):
 target=root/name
 if target.exists():raise SystemExit('Refusing existing '+str(target))
 shutil.copytree(source,target,ignore=shutil.ignore_patterns('.git','.godot'))
 patch=Path('$REPO/tests/outside/breakout/changes')/(name+'.patch')
 env=dict(os.environ,GIT_CEILING_DIRECTORIES=str(root))
 for args in (['--check'],[],['--reverse','--check']):subprocess.run(['git','apply',*args,str(patch)],cwd=target,env=env,check=True)
 print(name,'patch applied and reverse-check passed;',hashlib.sha256((target/'scripts/paddle.gd').read_bytes()).hexdigest())
