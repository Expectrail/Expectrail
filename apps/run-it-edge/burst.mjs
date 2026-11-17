// Exercise the actual Worker adapter and admission code, offline. No deployed request,
// credential, real dispatch, or model is used. Only GitHub transport/storage/clock are supplied.
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import worker, { RunIt } from './worker.js';
import { STATUS_TTL_MS } from './service.js';

if (!globalThis.crypto) Object.defineProperty(globalThis, 'crypto', { value: webcrypto });
const FIXTURE_TOKEN = 'local-scripted-token-not-a-secret';
const ORIGIN = 'https://expectrail.tech';
const root = 'https://api.github.com/repos/Expectrail/Expectrail/actions';

function fixture() {
  const values = new Map(), runs = new Map();
  let t = Date.UTC(2026, 10, 17, 12), next = 1, dispatches = 0, calls = 0;
  const storage = {
    async get(key) { return values.has(key) ? structuredClone(values.get(key)) : undefined; },
    async put(key, value) {
      const entries = typeof key === 'string' ? { [key]: value } : key;
      for (const [k, v] of Object.entries(structuredClone(entries))) values.set(k, v);
    },
    async delete(key) { values.delete(key); },
  };
  const json = (status, doc) => new Response(doc === undefined ? null : JSON.stringify(doc), { status });
  const fakeFetch = async (input, options = {}) => {
    const url = String(input), method = options.method || 'GET'; calls++;
    assert.equal(options.redirect, 'manual');  // Workers accept only follow or manual (#595)
    if (method === 'POST' && url === root + '/workflows/run-it.yml/dispatches') {
      assert.equal(options.headers.Authorization, 'Bearer ' + FIXTURE_TOKEN);
      const body = JSON.parse(options.body);
      assert.deepEqual(Object.keys(body).sort(), ['inputs', 'ref']);
      assert.equal(body.ref, 'main');
      assert.deepEqual(Object.keys(body.inputs).sort(), ['request_id', 'sample']);
      const id = body.inputs.request_id;
      runs.set(id, { id: next++, status: 'queued', conclusion: null, phase: 'completed' });
      dispatches++;
      return json(204);
    }
    assert.equal(method, 'GET', 'transport stub refuses every other method');
    if (url.startsWith(root + '/workflows/run-it.yml/runs?')) {
      return json(200, { workflow_runs: [...runs].map(([id, run]) => ({ id: run.id, display_title: 'Run it ' + id })) });
    }
    const match = new RegExp('^' + root.replaceAll('.', '\\.') + '/runs/([0-9]+)$').exec(url);
    if (match) {
      const run = [...runs.values()].find(r => r.id === Number(match[1])); assert.ok(run);
      return json(200, { status: run.status, conclusion: run.conclusion });
    }
    const published = /^https:\/\/raw\.githubusercontent\.com\/Expectrail\/Expectrail\/run-it-results\/([a-z0-9-]{1,40})\/status\.json$/.exec(url);
    if (published) {
      const run = runs.get(published[1]); assert.ok(run);
      return json(200, { phase: run.phase });
    }
    throw new Error('No external transport is permitted: ' + method + ' ' + url);
  };
  let env = { GITHUB_TOKEN: FIXTURE_TOKEN, VISITOR_SALT: 'local-burst-salt-not-a-secret-0000000000', RUN_IT_OPEN: 'true' };
  let object;
  const namespace = {
    idFromName(name) { assert.equal(name, 'run-it'); return name; },
    get(id) { assert.equal(id, 'run-it'); return { fetch: request => object.fetch(request) }; },
  };
  function restart(extra = {}) {
    env = { ...env, ...extra };
    object = new RunIt({ storage }, env);
  }
  const originalFetch = globalThis.fetch, originalNow = Date.now, originalLog = console.log;
  globalThis.fetch = fakeFetch; Date.now = () => t;
  // Worker logging is retained separately, so stdout remains one machine-readable summary.
  const logs = [];
  console.log = message => logs.push(String(message));
  restart();
  async function request(method, path, visitor = '2001:db8::1') {
    const headers = { Origin: ORIGIN, 'CF-Connecting-IP': visitor, 'Content-Type': 'application/json' };
    const res = await worker.fetch(new Request('https://worker.invalid' + path, {
      method, headers, body: method === 'POST' ? JSON.stringify({ sample: 'clean' }) : undefined,
    }), { ...env, RUN_IT: namespace });
    return { status: res.status, body: await res.json() };
  }
  async function finish(id, failed = false, publishedFailure = false) {
    const run = runs.get(id); assert.ok(run);
    run.status = 'completed'; run.conclusion = failed ? 'failure' : 'success';
    run.phase = publishedFailure ? 'failed' : 'completed'; t += STATUS_TTL_MS + 1;
    const result = await request('GET', '/status/' + id);
    assert.equal(result.status, 200);
    assert.equal(result.body.state, failed ? 'failed' : 'published');
  }
  async function burst(count, visitor = () => '2001:db8::1') {
    return Promise.all(Array.from({ length: count }, (_, i) => request('POST', '/run', visitor(i))));
  }
  return {
    burst, finish, request, restart, values, logs,
    nextDay() { t = Date.UTC(2026, 10, 18, 0, 0, 1); },
    counts() { return { fakeDispatches: dispatches, fakeTransportCalls: calls }; },
    close() { globalThis.fetch = originalFetch; Date.now = originalNow; console.log = originalLog; },
  };
}

function tally(rows) {
  const result = { accepted: 0, busy: 0, visitorQuota: 0, dailyCap: 0, circuitOpen: 0 };
  for (const row of rows) {
    if (row.status === 202 && row.body.kind === 'accepted') result.accepted++;
    else if (row.status === 409 && row.body.reason === 'busy') result.busy++;
    else if (row.status === 429 && row.body.reason === 'visitor-quota') result.visitorQuota++;
    else if (row.status === 429 && row.body.reason === 'daily-cap') result.dailyCap++;
    else if (row.status === 503 && row.body.reason === 'circuit-open') result.circuitOpen++;
    else assert.fail('Unexpected refusal or response: ' + JSON.stringify(row));
  }
  return result;
}
function accepted(rows) { const found = rows.filter(r => r.status === 202); assert.equal(found.length, 1); return found[0].body.requestId; }

export async function measure() {
  const result = { scope: 'Actual worker.js and service.js; scripted local storage, clock and GitHub responses; zero external requests.', limits: { perVisitor: 3, daily: 40, consecutiveFailures: 3 } };
  let f = fixture();
  try {
    const all = [];
    for (let wave = 0; wave < 3; wave++) {
      const rows = await f.burst(200); all.push(...rows); await f.finish(accepted(rows));
      if (wave === 1) f.restart(); // quota survives an object restart
    }
    all.push(...await f.burst(200));
    assert.deepEqual(tally(all), { accepted: 3, busy: 597, visitorQuota: 200, dailyCap: 0, circuitOpen: 0 });
    assert.equal(f.counts().fakeDispatches, 3);
    assert.ok(all.slice(-200).every(r => r.body.resetsAt === '2026-11-18T00:00:00Z'));
    const saved = JSON.stringify([...f.values]); assert.ok(!saved.includes('2001:db8::1'), 'visitor address must not be stored raw');
    result.perVisitor = { requests: all.length, ...tally(all), restartPreservedQuota: true, rawAddressStored: false };
    f.nextDay(); const reopened = await f.burst(1); await f.finish(accepted(reopened));
    result.perVisitor.midnightResetAccepted = 1; result.perVisitor.transport = f.counts();
  } finally { f.close(); }
  f = fixture();
  try {
    const all = [];
    for (let wave = 0; wave < 40; wave++) {
      const rows = await f.burst(25, i => `2001:db8:${wave.toString(16)}::${i.toString(16)}`);
      all.push(...rows); await f.finish(accepted(rows));
      if (wave === 19) f.restart();
    }
    all.push(...await f.burst(200, i => '2001:db8:ffff::' + i.toString(16)));
    assert.deepEqual(tally(all), { accepted: 40, busy: 960, visitorQuota: 0, dailyCap: 200, circuitOpen: 0 });
    assert.equal(f.counts().fakeDispatches, 40);
    assert.ok(all.slice(-200).every(r => r.body.resetsAt === '2026-11-18T00:00:00Z'));
    result.daily = { requests: all.length, ...tally(all), restartPreservedQuota: true };
    f.nextDay(); const reopened = await f.burst(1); await f.finish(accepted(reopened)); result.daily.midnightResetAccepted = 1; result.daily.transport = f.counts();
  } finally { f.close(); }
  f = fixture();
  try {
    const all = [];
    for (let wave = 0; wave < 3; wave++) {
      const rows = await f.burst(200, i => `2001:db8:${wave.toString(16)}::${i.toString(16)}`);
      all.push(...rows); await f.finish(accepted(rows), wave === 0, wave !== 0);
    }
    f.restart(); all.push(...await f.burst(200, i => '2001:db8:ffff::' + i.toString(16)));
    assert.deepEqual(tally(all), { accepted: 3, busy: 597, visitorQuota: 0, dailyCap: 0, circuitOpen: 200 });
    assert.equal(f.counts().fakeDispatches, 3);
    result.breaker = { requests: all.length, ...tally(all), failedRuns: 3, restartPreservedBreaker: true };
    f.nextDay(); assert.equal((await f.burst(1))[0].body.reason, 'circuit-open'); result.breaker.midnightDoesNotReset = true;
    f.restart({ BREAKER_EPOCH: 'scripted-manual-reset' }); const reopened = await f.burst(1); await f.finish(accepted(reopened)); result.breaker.epochResetAccepted = 1; result.breaker.transport = f.counts();
  } finally { f.close(); }
  result.primaryBurstRequests = result.perVisitor.requests + result.daily.requests + result.breaker.requests;
  result.controlPostRequests = 4;
  result.totalPostRequests = result.primaryBurstRequests + result.controlPostRequests;
  result.realExternalRequests = 0;
  return result;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log(JSON.stringify(await measure(), null, 2));
}
