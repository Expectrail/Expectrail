// Native workerd executes the unchanged Worker/DO/service. Every outbound fetch is intercepted;
// the host callback implements only fake GitHub endpoints and never opens an external connection.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { createServer } from 'node:http';
import { runtime, COMPATIBILITY_DATE } from './runtime-check.mjs';
import { STATUS_TTL_MS, STATUS_REFRESH_MS } from '../service.js';

const installed=runtime();
if (installed.missing && process.env.EXPECTRAIL_WORKER_TESTS==='required') throw new Error(installed.missing);
if (installed.info) console.log('Native runtime: '+JSON.stringify(installed.info));
const native=(name,fn)=>test(name,{skip:installed.missing||false,timeout:60000},fn);
const bodies=[];
after(()=>{if(process.env.BODIES_OUT)writeFileSync(process.env.BODIES_OUT,JSON.stringify(bodies));});
// Miniflare's host process also has a fetch path (Request.cf metadata). Disable that below and
// reject/count every non-loopback host HTTP attempt, including SDK calls outside Worker fetch.
if(installed.info){
  const {Dispatcher,getGlobalDispatcher,setGlobalDispatcher}=installed.undici;
  const previous=getGlobalDispatcher(),attempts=[];
  class LoopbackOnly extends Dispatcher{
    dispatch(options,handler){
      const host=new URL(String(options.origin)).hostname;
      if(['127.0.0.1','localhost','[::1]','::1'].includes(host))return previous.dispatch(options,handler);
      attempts.push(host);queueMicrotask(()=>handler.onError(new Error('Host non-loopback HTTP is disabled')));return false;
    }
  }
  // Preserve the SDK's existing connection pools; the guard changes only egress permission.
  setGlobalDispatcher(new LoopbackOnly());
  after(()=>{setGlobalDispatcher(previous);assert.deepEqual(attempts,[],
    'the host SDK attempted non-loopback HTTP');console.log('Host non-loopback HTTP attempts: '+attempts.length);});
}
const EDGE=fileURLToPath(new URL('../',import.meta.url));
const ORIGIN='https://expectrail.tech';
const TOKEN='local-runtime-token-not-a-secret';
const FORMAT='expectrail.run-it-api/v1';
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return{promise,resolve};};
async function within(promise,ms=1200){
  let timer;
  try{return await Promise.race([promise,new Promise(r=>{timer=setTimeout(()=>r(null),ms);})]);}
  finally{clearTimeout(timer);}
}

function fixture({redirect=false,mutate=false}={}){
  const f={calls:[],dispatches:0,rid:null,runStatus:'queued',verifyDone:false,mode:'normal',bodies:[]};
  const json=doc=>new Response(JSON.stringify(doc),{status:200});
  const pending=[];
  async function fake(request){
    const url=new URL(request.url),method=request.method;
    f.calls.push(method+' '+request.url);
    assert.equal(request.headers.get('User-Agent'),'expectrail-run-it');
    const api='/repos/Expectrail/Expectrail/actions';
    if(url.hostname==='api.github.com'){
      assert.equal(request.headers.get('Authorization'),'Bearer '+TOKEN);
      if(method==='POST' && url.pathname===api+'/workflows/run-it.yml/dispatches'){
        if(redirect)return new Response(null,{status:302,headers:{Location:'https://never-follow.invalid/'}});
        const doc=await request.json();
        assert.deepEqual(Object.keys(doc).sort(),['inputs','ref']);assert.equal(doc.ref,'main');
        assert.deepEqual(Object.keys(doc.inputs).sort(),['request_id','sample']);assert.equal(doc.inputs.sample,'clean');
        f.rid=doc.inputs.request_id;assert.match(f.rid,/^[a-z0-9-]{1,40}$/);f.dispatches++;
        return new Response(null,{status:204});
      }
      assert.equal(method,'GET');
      if(f.mode==='three-slow')await delay(800);
      if(url.pathname===api+'/workflows/run-it.yml/runs'){
        assert.equal(url.searchParams.get('event'),'workflow_dispatch');assert.equal(url.searchParams.get('branch'),'main');
        return json({workflow_runs:[{id:101,display_title:'Run it '+f.rid}]});
      }
      if(url.pathname===api+'/runs/101'){
        if(f.mode==='body-hangs'){
          let controller,closed=false;
          const stream=new ReadableStream({start(c){controller=c;c.enqueue(new TextEncoder().encode('{'));},cancel(){closed=true;}});
          f.bodies.push(()=>{if(!closed){closed=true;controller.enqueue(new TextEncoder().encode('"status":"completed","conclusion":"failure"}'));controller.close();}});
          return new Response(stream,{status:200});
        }
        return json({status:f.runStatus,conclusion:f.runStatus==='completed'?'success':null});
      }
      if(url.pathname===api+'/runs/101/jobs'){
        assert.equal(url.searchParams.get('per_page'),'10');
        return json({jobs:[{name:'verify',status:f.verifyDone?'completed':'in_progress',conclusion:f.verifyDone?'success':null}]});
      }
    }
    if(url.hostname==='raw.githubusercontent.com' && method==='GET' &&
       url.pathname==='/Expectrail/Expectrail/run-it-results/'+f.rid+'/status.json'){
      assert.equal(request.headers.get('Authorization'),null);return json({phase:'completed'});
    }
    throw new Error('Outbound request outside fake GitHub allowlist: '+method+' '+request.url);
  }
  let service=readFileSync(EDGE+'service.js','utf8');
  if(mutate){assert.ok(service.includes('redirect: "manual"'));service=service.replace('redirect: "manual"','redirect: "error"');}
  const mf=new installed.Miniflare({
    name:'expectrail-runtime-test',host:'127.0.0.1',port:0,compatibilityDate:COMPATIBILITY_DATE,cf:false,
    modules:[{type:'ESModule',path:EDGE+'worker.js'},{type:'ESModule',path:EDGE+'service.js',contents:service}],
    durableObjects:{RUN_IT:{className:'RunIt',useSQLite:true}},
    bindings:{GITHUB_TOKEN:TOKEN,VISITOR_SALT:'local-runtime-salt-not-a-secret-000000000',RUN_IT_OPEN:'true'},
    outboundService:fake,
  });
  f.call=(path,method='GET')=>{
    const promise=(async()=>{
      const response=await mf.dispatchFetch('http://worker.invalid'+path,{method,headers:{Origin:ORIGIN,'CF-Connecting-IP':'2001:db8::1'},
        body:method==='POST'?'{"sample":"clean"}':undefined});
      const doc=await response.json();bodies.push(doc);
      assert.equal(doc.format,FORMAT);assert.equal(response.headers.get('Access-Control-Allow-Origin'),ORIGIN);
      return{code:response.status,doc};
    })();
    pending.push(promise);return promise;
  };
  f.close=async()=>{f.bodies.forEach(release=>release());await mf.dispose();await Promise.allSettled(pending);};
  f.release=()=>f.bodies.forEach(release=>release());
  return f;
}

async function start(f){
  const response=await f.call('/run','POST');assert.equal(response.code,202);
  assert.equal(response.doc.kind,'accepted');
  assert.equal(f.dispatches,1,'fake GitHub must actually receive exactly one dispatch');
  return response.doc.requestId;
}

native('workerd runs the actual Worker and SQLite Durable Object through all healthy phases',async()=>{
  const f=fixture();
  try{
    const health=await f.call('/health');assert.equal(health.code,200);assert.equal(health.doc.open,true);assert.equal(health.doc.standIn,false);
    const id=await start(f);assert.equal((await f.call('/status/'+id)).doc.state,'queued');
    assert.equal(f.calls.length,1,'fresh reservations need no GitHub read');
    for(const [status,verify,state]of[['in_progress',false,'running'],['in_progress',true,'publishing'],['completed',true,'published']]){
      f.runStatus=status;f.verifyDone=verify;await delay(STATUS_TTL_MS+50);
      const result=await f.call('/status/'+id);assert.equal(result.doc.state,state);assert.equal(result.doc.requestId,id);
      assert.ok(!('decision'in result.doc)&&!('verdict'in result.doc));
    }
    assert.equal(f.dispatches,1);
  }finally{await f.close();}
});

native('workerd coalesces slow three-read refreshes, answers promptly and recovers without redispatch',async()=>{
  const f=fixture();
  try{
    const id=await start(f);f.runStatus='in_progress';f.mode='three-slow';await delay(STATUS_TTL_MS+50);
    const begin=performance.now();
    const elapsed=[];
    const answers=await within(Promise.all(Array.from({length:30},()=>f.call('/status/'+id).then(result=>{
      elapsed.push(performance.now()-begin);return result;
    }))));
    if(answers===null)console.log('Slow batch diagnostic: '+JSON.stringify({elapsedMs:elapsed,providerCalls:f.calls}));
    assert.notEqual(answers,null,'native status exceeded its prompt-response bound');
    console.log('Native poll batch: '+JSON.stringify({requests:answers.length,elapsedMs:performance.now()-begin}));
    assert.ok(answers.every(r=>r.code===200&&r.doc.state==='queued'));
    assert.ok(performance.now()-begin<1200);
    await delay(STATUS_REFRESH_MS+500);
    assert.equal(f.calls.filter(c=>c.startsWith('GET ')).length,3,'one refresh, not thirty');
    assert.equal((await f.call('/status/'+id)).doc.state,'queued','no failure inferred from deadline');
    assert.equal((await f.call('/run','POST')).doc.reason,'busy');assert.equal(f.dispatches,1);
    f.mode='normal';await delay(STATUS_TTL_MS+50);
    assert.equal((await f.call('/status/'+id)).doc.state,'running');assert.equal(f.dispatches,1);
    assert.equal(f.calls.filter(c=>c.includes('/workflows/run-it.yml/runs?')).length,1,'confirmed id survives the timeout');
  }finally{await f.close();}
});

native('workerd bounds response bodies and a late failure cannot replace the cached state',async()=>{
  const f=fixture();
  try{
    const id=await start(f);f.runStatus='in_progress';f.mode='body-hangs';await delay(STATUS_TTL_MS+50);
    const answer=await within(f.call('/status/'+id));assert.notEqual(answer,null);assert.equal(answer.doc.state,'queued');
    await delay(STATUS_REFRESH_MS+300);f.release();await delay(50);
    assert.equal((await f.call('/status/'+id)).doc.state,'queued');
    assert.equal((await f.call('/run','POST')).doc.reason,'busy');assert.equal(f.dispatches,1);
  }finally{await f.close();}
});

native('workerd refuses an actual redirect response without following it',async()=>{
  const f=fixture({redirect:true});
  try{const answer=await f.call('/run','POST');assert.equal(answer.code,502);assert.equal(answer.doc.reason,'unavailable');
    assert.equal(f.calls.length,1);assert.equal(f.dispatches,0);
  }finally{await f.close();}
});

native('the dispatch assertion catches redirect error on workerd, which Node alone accepts',async()=>{
  let hits=0;
  const server=createServer((request,response)=>{hits++;response.writeHead(204);response.end();});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try{
    const answer=await fetch('http://127.0.0.1:'+server.address().port+'/',{redirect:'error'});
    assert.equal(answer.status,204);await answer.arrayBuffer();assert.equal(hits,1);
  }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
  const f=fixture({mutate:true});
  try{await assert.rejects(()=>start(f),/fake GitHub must actually receive exactly one dispatch/);
    assert.equal(f.calls.length,0,'the runtime rejects redirect error before the fake provider');
  }finally{await f.close();}
});
