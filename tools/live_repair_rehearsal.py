"""Offline localhost rehearsal of the actual CLI; never a live provider transport.

Only the HTTP socket destinations change. Replays, checks, evaluators, the fix
loop and gate decisions are the production implementations. Vision responses
are scripted detections, not model-quality evidence.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from tools import live_repair_kit as kit


def install_offline_transport():
    """Trusted subprocess bootstrap only; no production env switch enables this."""
    real_build=urllib.request.build_opener
    provider=os.environ['REHEARSAL_PROVIDER'];vision=os.environ['REHEARSAL_VISION']
    for value in (provider,vision):
        if urlsplit(value).hostname!='127.0.0.1':raise ValueError('rehearsal must stay on localhost')
    def build(*handlers):
        opener=real_build(*handlers);original=opener.open
        def offline(req,*args,**kwargs):
            if isinstance(req,str):req=urllib.request.Request(req)
            parsed=urlsplit(req.full_url)
            if parsed.netloc=='api.openai.com' and (parsed.path.startswith('/v1/models/') or parsed.path=='/v1/chat/completions'):
                target=provider
            elif parsed.netloc=='api.meta.ai' and parsed.path=='/v1/responses':target=vision
            else:raise RuntimeError('offline rehearsal refused non-fixture route')
            local=urllib.request.Request(target+parsed.path,data=req.data,headers=dict(req.header_items()),method=req.get_method())
            return original(local,*args,**kwargs)
        opener.open=offline
        return opener
    urllib.request.build_opener=build
    urllib.request.urlopen=lambda req,*a,**kw:build(urllib.request.ProxyHandler({})).open(req,*a,**kw)


def robot_box(data):
    # Lazy optional dependency: ordinary module/test discovery needs no Pillow.
    from PIL import Image
    image=Image.open(io.BytesIO(data)).convert('RGB');w,h=image.size
    x0=max(0,w//2-140);crop=image.crop((x0,h//2,min(w,w//2+140),h))
    mask=Image.new('L',crop.size)
    pixels=crop.get_flattened_data() if hasattr(crop,'get_flattened_data') else crop.getdata()
    mask.putdata([255 if 20<r<120 and r*1.2<g<220 and g<b<235 else 0 for r,g,b in pixels])
    box=mask.getbbox()
    return ([box[0]+x0,box[1]+h//2,box[2]+x0,box[3]+h//2] if box else None),(w,h)


class Servers:
    def __init__(self,folder,ending):
        self.folder=Path(folder);self.ending=ending;self.lock=threading.Lock();self.events=[];self.servers=[]
    def log(self,kind,method,path,body,status):
        event={'sequence':len(self.events)+1,'kind':kind,'method':method,'path':path,
            'bodyBytes':len(body),'bodySha256':hashlib.sha256(body).hexdigest(),'status':status}
        with self.lock:
            event['sequence']=len(self.events)+1;self.events.append(event)
            with (self.folder/'requests.jsonl').open('a') as f:f.write(json.dumps(event)+'\n');f.flush();os.fsync(f.fileno())
    def start(self,kind):
        owner=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                owner.log(kind,'GET',self.path,b'',200)
                self.answer(200,{'id':kit.MODEL,'object':'model','owned_by':'offline-stand-in'})
            def do_POST(self):
                body=self.rfile.read(int(self.headers.get('Content-Length','0')))
                data=json.loads(body)
                if kind=='fixer':
                    status=500 if owner.ending=='cap' else 200
                    owner.log(kind,'POST',self.path,body,status)
                    # Public request body only. Never log Authorization headers.
                    (owner.folder/('fixer-request-'+str(len(owner.events))+'.json')).write_bytes(body)
                    patch=(kit.ROOT/'agents/fixtures/fix-collision-mask.patch').read_text()
                    if owner.ending=='reject':patch=patch.replace('+collision_mask = 30','+collision_mask = 15')
                    self.answer(status,{'choices':[{'message':{'content':patch}}],
                        'usage':{'prompt_tokens':100,'completion_tokens':100}})
                else:
                    content=data['input'][0]['content'];prompt=next(x['text'] for x in content if x['type']=='input_text')
                    encoded=next(x['image_url'] for x in content if x['type']=='input_image')
                    box,size=robot_box(base64.b64decode(encoded.split(',',1)[1]))
                    # Box/point requests ask where the object is. This fixture reports
                    # the same pixel-derived robot, with no trace or verdict access.
                    text='<0f>'
                    if box:
                        a,b,c,d=box;w,h=size
                        text+=f'1<|box;x1={a};y1={b};x2={c-1};y2={d-1};w={w};h={h};c=0.99|>'
                    owner.log(kind,'POST',self.path,body,200)
                    self.answer(200,{'status':'completed','output_text':text})
            def answer(self,status,doc):
                data=json.dumps(doc).encode();self.send_response(status)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        threading.Thread(target=server.serve_forever,daemon=True).start();self.servers.append(server)
        return 'http://127.0.0.1:'+str(server.server_address[1])
    def close(self):
        for server in self.servers:server.shutdown();server.server_close()


def rehearse(folder,ending, *, cap=None):
    folder=Path(folder).resolve();project=kit.prepare(folder)
    args=kit.parser().parse_args(['--out',str(folder)])
    if cap is not None:args.fixer_invocation=kit.amount(cap)
    # These are stand-in ledgers; each case is isolated, never the live month.
    env={k:v for k,v in os.environ.items() if not k.startswith('EXPECTRAIL_')}
    env.update(EXPECTRAIL_MODEL_MONTH_LEDGER=str(folder.parent/(ending+'-model-month.json')),
        EXPECTRAIL_VISION_MONTH_LEDGER=str(folder.parent/(ending+'-vision-month.json')),
        EXPECTRAIL_FIXER_API_KEY='offline-fixer-key',MODEL_API_KEY='offline-vision-key')
    original=os.environ.copy()
    try:
        os.environ.clear();os.environ.update(env);env=kit.environment(args)
    finally:os.environ.clear();os.environ.update(original)
    bootstrap=folder/'bootstrap';bootstrap.mkdir()
    (bootstrap/'sitecustomize.py').write_text('from tools.live_repair_rehearsal import install_offline_transport\ninstall_offline_transport()\n')
    env['PYTHONPATH']=str(bootstrap)+os.pathsep+str(kit.ROOT)
    servers=Servers(folder,ending)
    try:
        env['REHEARSAL_PROVIDER']=servers.start('fixer');env['REHEARSAL_VISION']=servers.start('vision')
        argv=kit.command(folder,args)
        (folder/'command.json').write_text(json.dumps(['expectrail',*argv[3:]],indent=2)+'\n')
        (folder/'plan.json').write_text(json.dumps(kit.plan(args),indent=2)+'\n')
        with (folder/'command.stdout.json').open('w') as stdout,(folder/'command.stderr.log').open('w') as stderr:
            proc=subprocess.run(argv,env=env,stdout=stdout,stderr=stderr)
    finally:servers.close()
    text=(folder/'command.stdout.json').read_text()
    try:doc=json.loads(text)
    except ValueError:doc=None
    summary={'ending':ending,'exit':proc.returncode,'repairRun':doc,
        'requests':len(servers.events),'fixerInferenceRequests':sum(e['kind']=='fixer' and e['method']=='POST' for e in servers.events),
        'visionRequests':sum(e['kind']=='vision' for e in servers.events),'liveCalls':0}
    (folder/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path)
    p.add_argument('--ending',choices=['accept','reject','cap','all'],default='all');p.add_argument('--cap')
    args=p.parse_args(argv)
    cases=['accept','reject','cap'] if args.ending=='all' else [args.ending]
    results=[]
    for ending in cases:
        cap=args.cap
        if ending=='cap' and cap is None and results:
            records=list((args.out/'accept'/'jobs').rglob('fixer-invocation.json'))
            value=json.loads(records[0].read_text())['requests'][0]['reservedNanoUsd']
            cap='6'  # One full-context request fits; its retry cannot fit.
        result=rehearse(args.out/ending,ending,cap=cap)
        proof=verify_evidence(args.out/ending,ending)
        (args.out/ending/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
        results.append(result)
        print(json.dumps({k:v for k,v in result.items() if k!='repairRun'}),flush=True)
    return 0 if all(r['repairRun'] and r['repairRun']['result']['decision']=={'accept':'accept','reject':'needs-review','cap':'needs-review'}[r['ending']] for r in results) else 1



def verify_evidence(folder,ending):
    """Assert the recorded gate and meter proofs; never make a new decision."""
    from expectrail import contracts,fixer_budget
    from expectrail.gate import record
    folder=Path(folder)
    doc=json.loads((folder/'command.stdout.json').read_text())
    paths=list((folder/'jobs/jobs').glob('*/repair-*/repair-run.json'))
    if len(paths)!=1:raise AssertionError('expected one repair-run')
    saved=contracts.load_strict(paths[0],'repair-run')
    assert doc==saved and doc['reproduction']['kind']=='approved' and doc['repairAttempted']
    assert len(doc['attempts'])==1
    prechecks=list((folder/'jobs/jobs').glob('*/output/playtest-precheck.log'))
    if not prechecks:prechecks=list((folder/'jobs/jobs').rglob('playtest-precheck.log'))
    pre=json.loads(prechecks[0].read_text())
    assert [r['run'] for r in pre]==[1,2,3]
    assert all(r['coverage']['reached']==[True] and any(c['result']=='fail' for c in r['checks']) for r in pre)
    row=doc['attempts'][0]
    meter=fixer_budget.read(paths[0].parent/row['fixerInvocation'])
    events=[json.loads(s) for s in (folder/'requests.jsonl').read_text().splitlines()]
    posts=[e for e in events if e['kind']=='fixer' and e['method']=='POST']
    assert len(posts)==meter['admittedRequests']==1
    assert posts[0]['bodySha256']==meter['requests'][0]['bodySha256']
    assert meter['reservedNanoUsd']<=meter['capNanoUsd']
    # Every received vision request has a pre-send $0.0025 hold in a worker budget.
    vision=sum(e['kind']=='vision' for e in events)
    worker_docs=[json.loads(p.read_text()) for p in (folder/'jobs/jobs').glob('*/status.json')]
    holds=sum(r['reservedUsd'] for d in worker_docs for r in d['budget']['phases'] if r['role']=='vision')
    assert abs(holds-vision*.0025)<1e-8,(holds,vision)
    if ending=='cap':
        assert doc['result']['decision']=='needs-review' and row['budgetStop']=='fixer-invocation-cap'
        assert meter['stopReason']=='fixer-invocation-cap' and meter['deniedRequests']>=1
        assert row['job'] is None and len([e for e in events if e['method']=='GET'])==1
    else:
        assert row['gateDecision']=={'accept':'accept','reject':'reject'}[ending]
        findings=record.read_record(folder/'jobs/jobs'/row['job']/'output/findings.json')
        assert findings['decision']==row['gateDecision']
        if ending=='accept':
            assert record.rule_of(findings)=='both' and findings['repair']['demonstrated']>0
            assert doc['result']['decision']=='accept'
        else:assert doc['result']['decision']=='needs-review'
    manifests=list((folder/'jobs/jobs').rglob('replay.json'))
    assert manifests
    for path in manifests:
        manifest=json.loads(path.read_text());assert manifest['isolation']['network']=='none'
        trace=json.loads((path.parent/'trace.json').read_text())
        if trace.get('viewport'):
            from agents.sam_observations import png_size
            frame=next((path.parent/'frames').glob('*.png'))
            assert list(png_size(frame))==trace['viewport']
    return {'ending':ending,'reproduction':'approved','repairAttempted':True,
        'gateDecision':row.get('gateDecision'),'result':doc['result']['decision'],
        'stop':doc['stop']['reason'],'fixerRequests':len(posts),'visionRequests':vision,
        'fixerReservedNanoUsd':meter['reservedNanoUsd'],'visionReservedUsd':round(holds,4),
        'replays':len(manifests),'observerRule':'both' if ending!='cap' else None,'liveCalls':0}


if __name__=='__main__':raise SystemExit(main())
