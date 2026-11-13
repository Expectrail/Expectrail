// Tests of the Run it edge function (#265, slice 3) with a fake GitHub, a memory store and a clock
// the test moves. No network: every fetch goes to the fake, which also checks that only the allowed
// endpoints are called. Run: node --test apps/run-it-edge/test/
//
// With BODIES_OUT set, every body the function sent is written there as JSON, so the Python suite
// (tests/test_runit_edge.py) can check each one against contracts/run-it-api.v1.schema.json.
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { createService, memoryStore, SAMPLES, STATUS_TTL_MS, LOST_AFTER_MS, GIVE_UP_MS } from "../service.js";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const ORIGIN = "https://expectrail.tech";
const bodies = [];
after(() => {
  if (process.env.BODIES_OUT) writeFileSync(process.env.BODIES_OUT, JSON.stringify(bodies));
});

const ALLOWED = [
  /^POST https:\/\/api\.github\.com\/repos\/Expectrail\/Expectrail\/actions\/workflows\/run-it\.yml\/dispatches$/,
  /^GET https:\/\/api\.github\.com\/repos\/Expectrail\/Expectrail\/actions\/workflows\/run-it\.yml\/runs\?event=workflow_dispatch&branch=main&per_page=50&created=%3E%3D[0-9TZ:-]+$/,
  /^GET https:\/\/api\.github\.com\/repos\/Expectrail\/Expectrail\/actions\/runs\/[0-9]+$/,
  /^GET https:\/\/api\.github\.com\/repos\/Expectrail\/Expectrail\/actions\/runs\/[0-9]+\/jobs\?per_page=10$/,
  /^GET https:\/\/raw\.githubusercontent\.com\/Expectrail\/Expectrail\/run-it-results\/[a-z0-9-]{1,40}\/status\.json$/,
];

// A fake GitHub: dispatches become runs the test moves along by hand.
function fakeGitHub() {
  const gh = { runs: new Map(), calls: [], dispatches: 0, nextId: 1000, failDispatch: false, failReads: false, hidden: false, maxActive: 0 };
  gh.active = () => [...gh.runs.values()].filter((r) => r.status !== "completed").length;
  gh.set = (requestId, status, conclusion = null, extra = {}) => Object.assign(gh.runs.get(requestId), { status, conclusion }, extra);
  gh.fetch = async (url, init = {}) => {
    const method = init.method || "GET";
    const line = `${method} ${url}`;
    gh.calls.push(line);
    assert.ok(ALLOWED.some((re) => re.test(line)), `an endpoint outside the allowlist: ${line}`);
    assert.match(init.headers?.["User-Agent"] || "", /expectrail-run-it/);
    const json = (status, doc) => new Response(doc === undefined ? null : JSON.stringify(doc), { status });
    if (method === "POST") {
      assert.equal(init.headers.Authorization, "Bearer test-token-0123456789abcdef");
      if (gh.failDispatch) return json(500, { message: "no" });
      const body = JSON.parse(init.body);
      assert.deepEqual(Object.keys(body).sort(), ["inputs", "ref"]);
      assert.equal(body.ref, "main");
      assert.deepEqual(Object.keys(body.inputs).sort(), ["request_id", "sample"]);
      gh.dispatches += 1;
      gh.runs.set(body.inputs.request_id, { id: gh.nextId++, sample: body.inputs.sample, status: "queued", conclusion: null, verify: "queued", phase: "completed" });
      gh.maxActive = Math.max(gh.maxActive, gh.active());
      return json(204);
    }
    if (gh.failReads) return json(502, { message: "bad gateway" });
    let m;
    if (url.includes("/workflows/run-it.yml/runs?")) {
      const list = gh.hidden ? [] : [...gh.runs.entries()].map(([rid, r]) => ({ id: r.id, display_title: `Run it ${rid}` }));
      return json(200, { workflow_runs: list });
    }
    if ((m = /\/actions\/runs\/([0-9]+)\/jobs/.exec(url))) {
      const r = [...gh.runs.values()].find((x) => x.id === Number(m[1]));
      return json(200, { jobs: [{ name: "verify", status: r.verify === "done" ? "completed" : "in_progress", conclusion: r.verify === "done" ? "success" : null }, { name: "publish", status: "queued" }] });
    }
    if ((m = /\/actions\/runs\/([0-9]+)$/.exec(url))) {
      const r = [...gh.runs.values()].find((x) => x.id === Number(m[1]));
      return json(200, { id: r.id, status: r.status, conclusion: r.conclusion });
    }
    if ((m = /run-it-results\/([a-z0-9-]+)\/status\.json$/.exec(url))) {
      const r = gh.runs.get(m[1]);
      if (!r || r.conclusion !== "success" || r.phase === null) return json(404);
      return json(200, { phase: r.phase });
    }
    throw new Error(`unhandled ${line}`);
  };
  return gh;
}

const ENV = { GITHUB_TOKEN: "test-token-0123456789abcdef", VISITOR_SALT: "s".repeat(40), RUN_IT_OPEN: "true" };

function setup(envExtra = {}, { store = memoryStore(), start = Date.UTC(2026, 10, 20, 15, 0, 0) } = {}) {
  const gh = fakeGitHub();
  const clock = { t: start };
  let n = 0;
  const make = (extra = envExtra) => createService({
    env: { ...ENV, ...extra }, store, fetch: gh.fetch, now: () => clock.t,
    newId: () => `00000000-0000-4000-8000-${String(++n).padStart(12, "0")}`,
  });
  const svc = make();
  async function call(method, path, { ip = "203.0.113.1", body, origin = ORIGIN, headers = {} } = {}) {
    const h = { ...headers };
    if (origin) h.Origin = origin;
    if (ip) h["CF-Connecting-IP"] = ip;
    if (body !== undefined) h["Content-Type"] = "application/json";
    const res = await svc.handle(new Request(`https://api.expectrail.tech${path}`, { method, headers: h, body }));
    const text = await res.text();
    const doc = text ? JSON.parse(text) : null;
    if (doc) bodies.push(doc);
    return { status: res.status, doc, headers: res.headers };
  }
  const run = (sample = "clean", opts = {}) => call("POST", "/run", { body: JSON.stringify({ sample }), ...opts });
  const status = (id) => call("GET", `/status/${id}`);
  // Finish a run on GitHub and let the service see it (the status cache is skipped by the clock).
  async function finish(id, conclusion = "success", phase = "completed") {
    gh.set(id, "completed", conclusion, { verify: "done", phase });
    clock.t += STATUS_TTL_MS + 1;
    return status(id);
  }
  return { gh, clock, svc, store, call, run, status, finish, make };
}

test("the service's sample ids are the manifest's", () => {
  const manifest = JSON.parse(readFileSync(join(REPO_ROOT, "docs/run-it/samples.json"), "utf8"));
  assert.deepEqual(SAMPLES, manifest.samples.map((s) => s.id));
});

test("a run is started, followed through its phases and published", async () => {
  const s = setup();
  const h = await s.call("GET", "/health");
  assert.deepEqual(h.doc, { format: "expectrail.run-it-api/v1", kind: "health", open: true, standIn: false });
  const a = await s.run("fall-through-bug");
  assert.equal(a.status, 202);
  assert.equal(a.doc.kind, "accepted");
  assert.equal(a.doc.sample, "fall-through-bug");
  assert.match(a.doc.requestId, /^[a-z0-9-]{1,40}$/);
  const id = a.doc.requestId;
  assert.equal(s.gh.runs.get(id).sample, "fall-through-bug");
  assert.equal((await s.status(id)).doc.state, "queued");
  s.gh.set(id, "in_progress");
  s.clock.t += STATUS_TTL_MS + 1;
  assert.equal((await s.status(id)).doc.state, "running");
  s.gh.set(id, "in_progress", null, { verify: "done" });
  s.clock.t += STATUS_TTL_MS + 1;
  assert.equal((await s.status(id)).doc.state, "publishing");
  const done = await s.finish(id);
  assert.equal(done.doc.state, "published");
  assert.equal(done.doc.kind, "status");
  assert.ok(!("decision" in done.doc) && !("verdict" in done.doc), "the service never sends a verdict");
  // The next visitor can start once it is published.
  assert.equal((await s.run("clean", { ip: "203.0.113.2" })).status, 202);
});

test("a burst of 200 at once starts exactly one run and refuses the rest as busy", async () => {
  const s = setup();
  const all = await Promise.all(Array.from({ length: 200 }, (_, i) => s.run(SAMPLES[i % 3], { ip: `198.51.100.${i % 250}` })));
  const accepted = all.filter((r) => r.status === 202);
  const busy = all.filter((r) => r.status === 409 && r.doc.reason === "busy");
  assert.equal(accepted.length, 1);
  assert.equal(busy.length, 199);
  assert.equal(s.gh.dispatches, 1);
  assert.ok(busy.every((r) => r.doc.retryAfterSeconds === 60 && r.headers.get("Retry-After") === "60"));
});

test("a scripted burst over a day holds every limit", async () => {
  // 120 rounds; in each, 30 requests at once from 12 visitors, then the run (if any) finishes.
  const s = setup({ DAILY_CAP: "40", PER_VISITOR: "3" });
  const perVisitor = new Map();
  const reasons = new Map();
  for (let round = 0; round < 120; round++) {
    const all = await Promise.all(Array.from({ length: 30 }, (_, i) => {
      const ip = `192.0.2.${(round * 7 + i) % 12}`;
      return s.run(SAMPLES[i % 3], { ip }).then((r) => ({ ...r, ip }));
    }));
    const accepted = all.filter((r) => r.status === 202);
    assert.ok(accepted.length <= 1, `round ${round}: ${accepted.length} accepted at once`);
    for (const r of all) reasons.set(r.doc.reason || r.doc.kind, (reasons.get(r.doc.reason || r.doc.kind) || 0) + 1);
    for (const r of accepted) {
      perVisitor.set(r.ip, (perVisitor.get(r.ip) || 0) + 1);
      await s.finish(r.doc.requestId);
    }
    s.clock.t += 1000;
  }
  assert.equal(s.gh.maxActive, 1, "never two runs on GitHub at once");
  assert.equal(s.gh.dispatches, 36, "12 visitors, 3 each: the visitor quota binds before the daily cap of 40");
  assert.ok([...perVisitor.values()].every((n) => n <= 3));
  assert.ok(reasons.get("visitor-quota") > 0);
  assert.ok(reasons.get("busy") > 0);
});

test("the daily cap holds for many visitors and resets at midnight UTC", async () => {
  const s = setup({ DAILY_CAP: "5" });
  for (let i = 0; i < 5; i++) {
    const a = await s.run("clean", { ip: `10.0.0.${i}` });
    assert.equal(a.status, 202);
    await s.finish(a.doc.requestId);
  }
  const refused = await s.run("clean", { ip: "10.0.0.99" });
  assert.equal(refused.status, 429);
  assert.equal(refused.doc.reason, "daily-cap");
  assert.equal(refused.doc.resetsAt, "2026-11-21T00:00:00Z");
  assert.equal(s.gh.dispatches, 5);
  s.clock.t = Date.UTC(2026, 10, 21, 0, 0, 1);
  assert.equal((await s.run("clean", { ip: "10.0.0.99" })).status, 202);
});

test("a visitor gets three runs a day, counted by a salted hash and never by the address", async () => {
  const s = setup();
  for (let i = 0; i < 3; i++) {
    const a = await s.run("clean", { ip: "203.0.113.7" });
    assert.equal(a.status, 202);
    await s.finish(a.doc.requestId);
  }
  const q = await s.run("clean", { ip: "203.0.113.7" });
  assert.equal(q.status, 429);
  assert.equal(q.doc.reason, "visitor-quota");
  assert.equal(q.doc.resetsAt, "2026-11-21T00:00:00Z");
  assert.equal((await s.run("clean", { ip: "203.0.113.8" })).status, 202);
  const stored = JSON.stringify([...s.store.map.entries()]);
  assert.ok(!stored.includes("203.0.113"), "no address is stored");
});

test("three failed runs in a row open the circuit breaker; a new BREAKER_EPOCH closes it", async () => {
  const s = setup();
  const outcomes = [["failure"], ["success", "failed"], ["cancelled"]];   // a failed phase published counts too
  for (const [i, [conclusion, phase]] of outcomes.entries()) {
    const a = await s.run("clean", { ip: `10.1.0.${i}` });
    assert.equal(a.status, 202);
    const done = await s.finish(a.doc.requestId, conclusion, phase || "completed");
    assert.equal(done.doc.state, { failure: "failed", success: "published", cancelled: "cancelled" }[conclusion]);
  }
  const open = await s.run("clean", { ip: "10.1.0.9" });
  assert.equal(open.status, 503);
  assert.equal(open.doc.reason, "circuit-open");
  assert.equal(open.doc.resetsAt, null);
  assert.equal((await s.call("GET", "/health")).doc.open, false);
  assert.equal(s.gh.dispatches, 3);
  // A person looks, then changes BREAKER_EPOCH: a fresh instance over the same storage starts again.
  const again = s.make({ BREAKER_EPOCH: "2026-11-20" });
  const res = await again.handle(new Request("https://api.expectrail.tech/run", {
    method: "POST", headers: { Origin: ORIGIN, "CF-Connecting-IP": "10.1.0.9", "Content-Type": "application/json" }, body: '{"sample":"clean"}',
  }));
  assert.equal(res.status, 202);
});

test("a success between failures resets the count; an unreadable result neither counts nor resets", async () => {
  const s = setup();
  // failed, failed, published and read (resets), failed, published but unreadable (no change), failed
  const seq = [["failure"], ["failure"], ["success", "completed"], ["failure"], ["success", null], ["failure"]];
  for (const [i, [conclusion, phase]] of seq.entries()) {
    const a = await s.run("clean", { ip: `10.2.0.${i}` });
    assert.equal(a.status, 202, `run ${i}`);
    await s.finish(a.doc.requestId, conclusion, phase === undefined ? "completed" : phase);
  }
  const third = await s.run("clean", { ip: "10.2.0.50" });
  assert.equal(third.status, 202, "2 failed in a row since the last success that was read");
  await s.finish(third.doc.requestId, "failure");
  assert.equal((await s.run("clean", { ip: "10.2.0.51" })).doc.reason, "circuit-open", "the unreadable one did not reset the count");
});

test("a run GitHub never lists is failed after five minutes, and frees the next visitor", async () => {
  const s = setup();
  s.gh.hidden = true;
  const a = await s.run("clean");
  assert.equal((await s.run("clean", { ip: "10.3.0.1" })).doc.reason, "busy");
  s.clock.t += LOST_AFTER_MS + 1;
  assert.equal((await s.status(a.doc.requestId)).doc.state, "failed");
  assert.equal((await s.run("clean", { ip: "10.3.0.1" })).status, 202);
});

test("a run still going after thirty minutes is failed, even when GitHub cannot be read", async () => {
  const s = setup();
  const a = await s.run("clean");
  s.gh.set(a.doc.requestId, "in_progress");
  s.gh.failReads = true;
  s.clock.t += STATUS_TTL_MS + 1;
  assert.equal((await s.status(a.doc.requestId)).doc.state, "queued", "GitHub unreadable: the last state is kept");
  s.clock.t += GIVE_UP_MS;
  assert.equal((await s.status(a.doc.requestId)).doc.state, "failed");
});

test("a dispatch GitHub refuses starts nothing and counts nothing", async () => {
  const s = setup({ PER_VISITOR: "1" });
  s.gh.failDispatch = true;
  const r = await s.run("clean");
  assert.equal(r.status, 502);
  assert.equal(r.doc.reason, "unavailable");
  s.gh.failDispatch = false;
  assert.equal((await s.run("clean")).status, 202, "the failed try did not use the visitor's one run");
});

test("polling is answered from the cache: GitHub is read at most once per ten seconds", async () => {
  const s = setup();
  const a = await s.run("clean");
  s.gh.set(a.doc.requestId, "in_progress");
  const before = s.gh.calls.length;
  await Promise.all(Array.from({ length: 100 }, () => s.status(a.doc.requestId)));
  assert.equal(s.gh.calls.length, before, "the start counts as a fresh read");
  s.clock.t += STATUS_TTL_MS + 1;
  await Promise.all(Array.from({ length: 100 }, () => s.status(a.doc.requestId)));
  assert.ok(s.gh.calls.length - before <= 3, `${s.gh.calls.length - before} reads for 100 polls`);
});

test("switched off, not set up, or misconfigured: every run is refused and health says closed", async () => {
  for (const [env, words] of [[{ RUN_IT_OPEN: "false" }, "switched off"], [{ RUN_IT_OPEN: "" }, "switched off"],
                              [{ GITHUB_TOKEN: "" }, "not set up"], [{ VISITOR_SALT: "short" }, "not set up"],
                              [{ DAILY_CAP: "lots" }, "not set up"], [{ ALLOWED_ORIGINS: "javascript:x" }, "not set up"]]) {
    const s = setup(env);
    const r = await s.run("clean");
    assert.equal(r.status, 503, JSON.stringify(env));
    assert.equal(r.doc.reason, "disabled");
    assert.ok(r.doc.detail.includes(words), r.doc.detail);
    assert.equal((await s.call("GET", "/health")).doc.open, false);
    assert.equal(s.gh.dispatches, 0);
  }
});

test("anything but a sample id from the list is refused before GitHub is called", async () => {
  const s = setup();
  const cases = [
    ["not json", "{", "bad-request"], ["an array", "[]", "bad-request"], ["null", "null", "bad-request"],
    ["extra key", '{"sample":"clean","ref":"x"}', "bad-request"], ["a number", '{"sample":1}', "bad-request"],
    ["unknown", '{"sample":"other"}', "unknown-sample"], ["a path", '{"sample":"../clean"}', "unknown-sample"],
    ["upper case", '{"sample":"CLEAN"}', "unknown-sample"], ["too large", JSON.stringify({ sample: "x".repeat(2000) }), "bad-request"],
    ["not utf-8", new Uint8Array([0x7b, 0xff, 0x7d]), "bad-request"],
  ];
  for (const [name, body, reason] of cases) {
    const r = await s.call("POST", "/run", { body });
    assert.equal(r.status, 400, name);
    assert.equal(r.doc.reason, reason, name);
  }
  for (const origin of [null, "https://evil.example", "https://expectrail.tech.evil.example"]) {
    const r = await s.call("POST", "/run", { body: '{"sample":"clean"}', origin });
    assert.equal(r.status, 403, String(origin));
    assert.equal(r.headers.get("Access-Control-Allow-Origin"), null);
  }
  for (const id of ["..%2F..%2Fx", "UPPER", "x".repeat(41), "00000000-0000-4000-8000-000000000999"]) {
    const r = await s.status(id);
    assert.equal(r.status, 404, id);
    assert.equal(r.doc.reason, "unknown-request");
  }
  assert.equal((await s.call("GET", "/other")).status, 404);
  assert.equal((await s.call("DELETE", "/run")).status, 404);
  assert.equal(s.gh.dispatches, 0);
  assert.equal(s.gh.calls.length, 0);
});

test("the page's origin may read the answers; preflight is answered", async () => {
  const s = setup();
  const pre = await s.svc.handle(new Request("https://api.expectrail.tech/run", { method: "OPTIONS", headers: { Origin: ORIGIN } }));
  assert.equal(pre.status, 204);
  assert.equal(pre.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  assert.equal(pre.headers.get("Access-Control-Allow-Headers"), "Content-Type");
  const h = await s.call("GET", "/api/health");
  assert.equal(h.status, 200, "the stub's /api/ paths work too");
  assert.equal(h.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  assert.equal(h.headers.get("Cache-Control"), "no-store");
  const other = await s.call("GET", "/health", { origin: "https://evil.example" });
  assert.equal(other.headers.get("Access-Control-Allow-Origin"), null);
});

test("old runs are forgotten beyond the last two hundred", async () => {
  const s = setup({ DAILY_CAP: "500", PER_VISITOR: "20" });
  let first = null;
  for (let i = 0; i < 205; i++) {
    const a = await s.run("clean", { ip: `10.9.${Math.floor(i / 20)}.1` });
    assert.equal(a.status, 202, `run ${i}`);
    first = first || a.doc.requestId;
    await s.finish(a.doc.requestId);
  }
  assert.equal((await s.status(first)).status, 404);
  assert.ok(s.store.map.size < 220);
});
