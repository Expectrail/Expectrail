from pathlib import Path
import shutil,subprocess
source=Path('/workspace/work/breakout-trial-source');game=Path('/workspace/work/breakout-pointer-source')
pin=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip();assert pin=='0ac7aed444ea593a023d9b666c211d7ab8acd51e',pin
subprocess.run(['git','diff','--exit-code'],cwd=source,check=True)
if game.exists():raise SystemExit('refusing existing trial folder')
# Copy only tracked source files from the pin, including assets. No previous config/route or imports.
files=subprocess.check_output(['git','ls-tree','-r','--name-only','HEAD'],cwd=source,text=True).splitlines()
for name in files:
 p=game/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,p)
print('Pinned source copied without prior Expectrail files:',pin,'files',len(files))
print('Source licence: MIT, 2025 Michele Pizzeghello; no source assets will be vendored.')
