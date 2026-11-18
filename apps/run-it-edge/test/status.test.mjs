// The real service, local transports only. Slow reads must not turn a reservation into a failure.
import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';
import { createService, memoryStore, STATUS_TTL_MS, GIVE_UP_MS } from '../service.js';

const ENV = {GITHUB_TOKEN: 'local-test-token-not-a-secret', VISITOR_SALT: 'local-test-salt-not-a-secret-000000000000', RUN_IT_OPEN: 'true'};
const RID = 'known-run';
const bodies=[];
after(()=>{if(process.env.BODIES_OUT)writeFileSync(process.env.BODIES_OUT,JSON.stringify(bodies));});
const T = Date.UTC(2026, 10, 17, 12);
const json = doc => new Response(JSON.stringify(doc), {status: 200});
const deferred = () => { let resolve; const promise = new Promise(r => {resolve=r;}); return {promise, resolve}; };
async function within(promise, ms=1000) {
  let timer;
  try { return await Promise.race([promise, new Promise(r => {timer=setTimeout(() => r(null),ms);})]); }
  finally { clearTimeout(timer); }
}
async function seeded(fetch, {state='queued', aged=true, runId=null}={}) {
  const store=memoryStore(), background=[], calls=[];
  await store.put('run:'+RID, {sample:'clean',state,checkedAt:T-STATUS_TTL_MS-1,updatedAt:T-1000,
    dispatchedAt:aged ? T-GIVE_UP_MS-1 : T-1000,runId});
  await store.put('active', RID);
  await store.put('breaker', {epoch:'0',failedInARow:2});
  const svc=createService({env:ENV,store,now:()=>T,waitUntil:p=>background.push(p),fetch:async(url,init)=>{
    assert.ok(url.startsWith('https://api.github.com/')||url.startsWith('https://raw.githubusercontent.com/'));
    calls.push({url,init}); return fetch(url,init);
  }});
  const status=async()=>{ const r=await svc.handle(new Request('https://worker.invalid/status/'+RID)); assert.equal(r.status,200); const doc=await r.json(); bodies.push(doc); return doc; };
  return {store,background,calls,svc,status};
}

test('one refresh budget covers findRun, run and jobs; a hundred polls get the last state promptly', async()=>{
  const s=await seeded(async url=>{
    await delay(800); // three successful reads would take 2.4s, beyond the whole refresh budget
    if(url.includes('/workflows/'))return json({workflow_runs:[{id:101,display_title:'Run it '+RID}]});
    if(url.includes('/jobs?'))return json({jobs:[]});
    return json({status:'in_progress',conclusion:null});
  });
  const start=performance.now(), requests=Promise.all(Array.from({length:100},()=>s.status()));
  try {
    const rows=await within(requests);
    assert.notEqual(rows,null,'status waited behind the GitHub refresh instead of returning its last known state');
    assert.ok(rows.every(r=>r.state==='queued'));
    assert.equal(s.background.length,1,'concurrent polls must coalesce one refresh');
    await s.background[0];
    assert.ok(performance.now()-start<2400,'the entire refresh must stop at its shared deadline');
    assert.equal(s.calls.length,3);
    assert.ok(s.calls.every(c=>c.init.signal===s.calls[0].init.signal),'one signal for the whole read sequence');
    assert.equal(s.calls[0].init.signal.aborted,true);
    const saved=await s.store.get('run:'+RID);
    assert.equal(saved.state,'queued','a slow read must not trigger the thirty-minute tracking failure');
    assert.equal(saved.runId,101,'a confirmed run id survives a later jobs timeout');
    assert.equal(await s.store.get('active'),RID);
    assert.equal((await s.store.get('breaker')).failedInARow,2);
    await s.status();assert.equal(s.calls.length,3,'timed-out attempts are also cached for the TTL');
  } finally {await requests;await Promise.all(s.background);}
});

test('a hanging JSON body is bounded and its late failure cannot change the run or breaker', async()=>{
  const body=deferred();
  const s=await seeded(async()=>({status:200,json:()=>body.promise}),{state:'running',runId:101});
  const request=s.status();
  try {
    const row=await within(request);
    assert.notEqual(row,null,'status waited for a hung body');assert.equal(row.state,'running');
    assert.equal(s.background.length,1);await s.background[0];
    assert.equal(s.calls[0].init.signal.aborted,true);
    body.resolve({status:'completed',conclusion:'failure'});await delay(20);
    assert.equal((await s.store.get('run:'+RID)).state,'running');
    assert.equal(await s.store.get('active'),RID);
    assert.equal((await s.store.get('breaker')).failedInARow,2);
    const response=await s.svc.handle(new Request('https://worker.invalid/run',{method:'POST',
      headers:{Origin:'https://expectrail.tech'},body:'{"sample":"clean"}'}));
    assert.equal(response.status,409);assert.equal((await response.json()).reason,'busy');
    assert.equal(s.calls.length,1,'no redispatch or retry while the active state is unknown');
  } finally {body.resolve({status:'in_progress',conclusion:null});await request;await Promise.all(s.background);}
});

test('published-phase JSON shares the budget and an unreadable phase never resets the breaker', async()=>{
  const body=deferred();
  const s=await seeded(async url=>url.includes('raw.githubusercontent.com') ? {status:200,json:()=>body.promise} :
    json({status:'completed',conclusion:'success'}),{runId:101,aged:false});
  const request=s.status();
  try {
    assert.notEqual(await within(request),null,'published-phase read held up the status answer');
    assert.equal(s.background.length,1);await s.background[0];
    assert.equal((await s.store.get('run:'+RID)).state,'published','GitHub completion was confirmed');
    assert.equal((await s.store.get('breaker')).failedInARow,2,'unknown phase neither counts nor resets');
    assert.equal(await s.store.get('active'),undefined);
    assert.equal(s.calls.length,2);assert.equal(s.calls[0].init.signal,s.calls[1].init.signal);
    body.resolve({phase:'failed'});await delay(20);
    assert.equal((await s.store.get('breaker')).failedInARow,2);
  } finally {body.resolve({phase:'completed'});await request;await Promise.all(s.background);}
});

test('a status answer does not queue behind a dispatch and never starts a second run', async()=>{
  const dispatched=deferred(), release=deferred(), store=memoryStore(), background=[];
  let time=T, posts=0;
  const svc=createService({env:ENV,store,now:()=>time,newId:()=>RID,waitUntil:p=>background.push(p),fetch:async(url,init)=>{
    if(init.method==='POST'){posts++;dispatched.resolve();await release.promise;return new Response(null,{status:204});}
    if(url.includes('/workflows/'))return json({workflow_runs:[{id:101,display_title:'Run it '+RID}]});
    if(url.includes('/jobs?'))return json({jobs:[]});
    return json({status:'in_progress',conclusion:null});
  }});
  const first=svc.handle(new Request('https://worker.invalid/run',{method:'POST',headers:{Origin:'https://expectrail.tech'},body:'{"sample":"clean"}'}));
  await dispatched.promise;time+=STATUS_TTL_MS+1;
  const status=svc.handle(new Request('https://worker.invalid/status/'+RID));
  try {
    const answer=await within(status);assert.notEqual(answer,null,'status was queued behind POST');
    assert.equal((await answer.json()).state,'queued');assert.equal(posts,1);
    assert.equal((await store.get('day')).total,1);
  } finally {release.resolve();await first;await status;await Promise.all(background);}
  assert.equal(posts,1);
});

test('fast confirmed failure still fails and opens the breaker', async()=>{
  const s=await seeded(async()=>json({status:'completed',conclusion:'failure'}),{runId:101,aged:false});
  assert.equal((await s.status()).state,'failed');
  assert.equal((await s.store.get('breaker')).failedInARow,3);
  assert.equal(await s.store.get('active'),undefined);
});

test('an unreadable provider response past the tracking limit keeps the known state and reservation', async()=>{
  const s=await seeded(async()=>new Response(null,{status:502}),{runId:101,state:'running'});
  assert.equal((await s.status()).state,'running');
  assert.equal(await s.store.get('active'),RID);
  assert.equal((await s.store.get('breaker')).failedInARow,2);
});
