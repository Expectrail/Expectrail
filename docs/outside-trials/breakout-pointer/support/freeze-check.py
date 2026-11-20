from pathlib import Path
import hashlib,json,subprocess
h=Path(__file__).parent;r=Path('$REPO');original=Path('$WORK/breakout-trial-source');copy=Path('$WORK/breakout-pointer-source')
freeze=json.loads((h/'PRODUCT_FREEZE.json').read_text());changed=[p for p,v in freeze.items() if hashlib.sha256((r/p).read_bytes()).hexdigest()!=v];assert not changed,changed
pin=subprocess.check_output(['git','rev-parse','HEAD'],cwd=original,text=True).strip();assert pin=='0ac7aed444ea593a023d9b666c211d7ab8acd51e'
subprocess.run(['git','diff','--exit-code'],cwd=original,check=True)
paths=subprocess.check_output(['git','ls-files','-z'],cwd=original).decode().split('\0');same=[]
for p in filter(None,paths):
 if (original/p).is_file():
  assert (original/p).read_bytes()==(copy/p).read_bytes(),p
  same.append(p)
result={'coreFilesUnchangedDuringTrial':len(freeze),'originalPin':pin,'pinnedGameTrackedFilesUnchanged':len(same),'noLiveModel':True,'approvalsAdded':False}
(h/'trial-freeze-check.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
