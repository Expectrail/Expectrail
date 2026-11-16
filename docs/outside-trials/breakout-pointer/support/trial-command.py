from pathlib import Path
import argparse,datetime,json,os,subprocess,time
h=Path(__file__).parent;r=Path('$REPO');docs=r/'docs/outside-trials/breakout-pointer'
p=argparse.ArgumentParser();p.add_argument('--label',required=True);p.add_argument('--tmpdir');p.add_argument('--cwd',default=str(r));p.add_argument('--timeout',type=int,default=240);p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args()
cmd=a.command[1:] if a.command[:1]==['--'] else a.command
ledger=docs/'commands.json';rows=json.loads(ledger.read_text()) if ledger.exists() else [];n=len(rows)+1;stem=f'{n:02d}-{a.label}';log=h/'trial-logs'/f'{stem}.log'
safe=('PATH','HOME','USER','LANG','LC_ALL','TMPDIR','DISPLAY','XAUTHORITY','HTTPS_PROXY','HTTP_PROXY','ALL_PROXY','NO_PROXY','https_proxy','http_proxy','all_proxy','no_proxy','SSL_CERT_FILE','SSL_CERT_DIR','GIT_SSL_CAINFO')
env={k:v for k,v in os.environ.items() if k in safe};env.update(PYTHONPATH=str(r),PYTHONUNBUFFERED='1',GIT_TERMINAL_PROMPT='0',EXPECTRAIL_GODOT='$WORK/dodge-tools/godot/Godot_v4.7.2-stable_linux.x86_64')
env['PATH']='$WORK/dodge-tools/display/usr/bin:'+env['PATH']
if a.tmpdir:
 for name in ('tmp','tools'):Path(a.tmpdir,name).mkdir(parents=True,exist_ok=True)
 env.update(TMPDIR=str(Path(a.tmpdir,'tmp')),EXPECTRAIL_TOOLS=str(Path(a.tmpdir,'tools')))
start=datetime.datetime.now(datetime.timezone.utc).isoformat();t=time.perf_counter()
with log.open('w') as out:
 try:
  proc=subprocess.run(cmd,cwd=a.cwd,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=a.timeout);code=proc.returncode;status='finished'
 except subprocess.TimeoutExpired:code=None;status='timeout';out.write('\nCOMMAND TIMED OUT\n')
row={'step':n,'label':a.label,'startedUtc':start,'command':cmd,'cwd':a.cwd,'seconds':time.perf_counter()-t,'exitCode':code,'status':status,'log':'trial-logs/'+log.name,'environment':{'EXPECTRAIL_GODOT':env['EXPECTRAIL_GODOT'],'TMPDIR':env.get('TMPDIR'),'EXPECTRAIL_TOOLS':env.get('EXPECTRAIL_TOOLS')}}
rows.append(row);ledger.write_text(json.dumps(rows,indent=2)+'\n');(h/'trial-logs'/f'{stem}.json').write_text(json.dumps(row,indent=2)+'\n');print(json.dumps(row),flush=True)
