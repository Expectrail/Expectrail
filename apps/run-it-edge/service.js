// The Run it edge function (#265, slice 3): the one thing between expectrail.tech and GitHub.
//
// It speaks expectrail.run-it-api/v1 (contracts/run-it-api.v1.schema.json), the contract the page and
// the local stub (tools/runit_stub.py) already use:
//
//   GET  /health                   {"kind": "health", "open": ..., "standIn": false}
//   POST /run   {"sample": id}     202 accepted with a request id minted here; or refused
//   GET  /status/<request id>      the run's state, read from GitHub; or refused (404)
//
// (The same paths under /api/ are accepted too, as the stub serves them.)
//
// What it holds: the only token, the quotas and the circuit breaker. What it never does: send a
// verdict (the verdict is the published status.json, which the page reads itself), take anything from
// the visitor but a sample id from the list below, or call any GitHub endpoint but the dispatch of
// run-it.yml on main and the reads of its runs.
//
// The platform is not fixed (Sean picks the host). This file uses only web-standard APIs (fetch,
// Request, Response, crypto) and takes its storage, clock and fetch as arguments; worker.js adapts it
// to a Workers-style runtime with one Durable Object, so every request sees the same state.

export const FORMAT = "expectrail.run-it-api/v1";
export const REPO = "Expectrail/Expectrail";
export const WORKFLOW = "run-it.yml";
export const REF = "main";
// docs/run-it/samples.json's ids. A test holds the two lists equal; the workflow checks again.
export const SAMPLES = ["clean", "fall-through-bug", "fall-through-repair", "recorded-fix"];
// Listed, but refused until its real recording exists and RECORDED_FIX_OPEN is "true".
export const UNRECORDED = new Set(["recorded-fix"]);
export const ID = /^[a-z0-9-]{1,40}$/;
export const MAX_BODY_BYTES = 1024;
// How long a status read from GitHub is reused, so visitors polling cannot spend the token's limit.
export const STATUS_TTL_MS = 10 * 1000;
// A status answer waits briefly for a fresh observation, then serves its last known state.
// All upstream reads in that refresh share one budget (including JSON bodies).
export const STATUS_RESPONSE_MS = 250;
export const STATUS_REFRESH_MS = 2000;
// A dispatched run that GitHub has not listed by then is lost: failed, no verdict.
export const LOST_AFTER_MS = 5 * 60 * 1000;
// verify's 15 minutes, publish's 5, and runner wait: a confirmed active run past this tracking limit
// is failed. An unreadable status keeps its last state and reservation, even beyond this age.
export const GIVE_UP_MS = 30 * 60 * 1000;
export const KEEP_RUNS = 200;
const ACTIVE = new Set(["queued", "running", "publishing"]);

const DEFAULTS = { perVisitor: 3, dailyCap: 40, breaker: 3 };

function intIn(raw, fallback, lo, hi) {
  if (raw === undefined || raw === null || raw === "") return fallback;
  const n = Number(raw);
  return Number.isInteger(n) && n >= lo && n <= hi ? n : null;
}

// The settings, read once from the environment. Anything missing or malformed closes the service:
// it never starts runs on a guess.
export function readConfig(env = {}) {
  const problems = [];
  const perVisitor = intIn(env.PER_VISITOR, DEFAULTS.perVisitor, 1, 20);
  const dailyCap = intIn(env.DAILY_CAP, DEFAULTS.dailyCap, 1, 500);
  const breaker = intIn(env.BREAKER, DEFAULTS.breaker, 1, 20);
  if (perVisitor === null) problems.push("PER_VISITOR is not a whole number from 1 to 20");
  if (dailyCap === null) problems.push("DAILY_CAP is not a whole number from 1 to 500");
  if (breaker === null) problems.push("BREAKER is not a whole number from 1 to 20");
  if (typeof env.GITHUB_TOKEN !== "string" || env.GITHUB_TOKEN.length < 20) problems.push("GITHUB_TOKEN is not set");
  if (typeof env.VISITOR_SALT !== "string" || env.VISITOR_SALT.length < 32) problems.push("VISITOR_SALT is not set (32 characters or more)");
  let origins = String(env.ALLOWED_ORIGINS || "https://expectrail.tech").split(",").map((s) => s.trim()).filter(Boolean);
  if (!origins.length || !origins.every((o) => /^https?:\/\/[a-z0-9.-]+(:[0-9]{1,5})?$/.test(o))) {
    problems.push("ALLOWED_ORIGINS is not a list of origins");
    origins = ["https://expectrail.tech"];
  }
  return {
    open: env.RUN_IT_OPEN === "true" && problems.length === 0,
    problems,
    perVisitor: perVisitor || DEFAULTS.perVisitor,
    dailyCap: dailyCap || DEFAULTS.dailyCap,
    breaker: breaker || DEFAULTS.breaker,
    // Changing BREAKER_EPOCH (to any new value) is how a person closes an open circuit breaker.
    breakerEpoch: String(env.BREAKER_EPOCH || "0").slice(0, 64),
    token: env.GITHUB_TOKEN,
    salt: env.VISITOR_SALT,
    origins,
    visitorHeader: String(env.VISITOR_HEADER || "CF-Connecting-IP"),
  };
}

export function iso(ms) {
  return new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");
}

function nextMidnight(ms) {
  const d = new Date(ms);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1);
}

function today(ms) {
  return iso(ms).slice(0, 10);
}

export function refusal(reason, detail, resetsAt = null, retryAfter = null) {
  return { format: FORMAT, kind: "refused", reason, detail: String(detail).slice(0, 300), resetsAt, retryAfterSeconds: retryAfter };
}

// A storage that keeps values in memory: tests and the local server. Same interface as worker.js's.
export function memoryStore() {
  const map = new Map();
  return {
    async get(key) { return map.has(key) ? structuredClone(map.get(key)) : undefined; },
    async put(key, value) { map.set(key, structuredClone(value)); },
    async putMany(entries) {
      const copy = structuredClone(entries);
      for (const [key, value] of Object.entries(copy)) map.set(key, value);
    },
    async delete(key) { map.delete(key); },
    map,
  };
}

// --- GitHub, the only endpoints this function calls ------------------------------------------------

// Race body reads too: a transport or test double may ignore an aborted signal.
// Late answers are observed but cannot resume the cancelled sequence or mutate service state.
function abortable(operation, signal) {
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise((resolve, reject) => {
    const clean = () => signal.removeEventListener("abort", abort);
    const abort = () => { clean(); reject(signal.reason); };
    signal.addEventListener("abort", abort, { once: true });
    Promise.resolve().then(() => {
      if (signal.aborted) throw signal.reason;
      return operation();
    }).then(value => { clean(); resolve(value); }, error => { clean(); reject(error); });
  });
}

export function github(token, fetchFn) {
  // Cloudflare Workers accept only "follow" or "manual" here: "error" makes every fetch throw before
  // it is sent (seen on the first open deploy, November 17). "manual" hands a redirect back as its
  // own response, which is never followed: dispatch refuses it below and read() requires 200.
  const options = signal => ({ redirect: "manual", signal: signal || AbortSignal.timeout(10_000) });
  const api = `https://api.github.com/repos/${REPO}/actions`;
  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "expectrail-run-it",
  };
  async function read(url, signal, authenticated = true) {
    const opts = options(signal);
    const r = await abortable(() => fetchFn(url, { ...opts, headers: authenticated ? headers : { "User-Agent": "expectrail-run-it" } }), opts.signal);
    if (r.status !== 200) throw new Error(`GitHub answered ${r.status}`);
    return abortable(() => r.json(), opts.signal);
  }
  return {
    async dispatch(sample, requestId) {
      const r = await fetchFn(`${api}/workflows/${WORKFLOW}/dispatches`, {
        ...options(), method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ ref: REF, inputs: { sample, request_id: requestId } }),
      });
      if (r.status !== 204 && r.status !== 200) {
        const error = new Error(`GitHub answered ${r.status}`);
        // A redirect is refused too: GitHub did not take the dispatch, so no run started.
        error.refused = [401, 403, 404, 422, 429].includes(r.status) || (r.status >= 300 && r.status < 400);
        throw error;
      }
    },
    // run-it.yml names each run "Run it <request id>", so the run is found by that name.
    async findRun(requestId, sinceMs, signal) {
      const since = iso(sinceMs - 60 * 1000);
      const doc = await read(`${api}/workflows/${WORKFLOW}/runs?event=workflow_dispatch&branch=${REF}&per_page=50&created=%3E%3D${since}`, signal);
      const runs = Array.isArray(doc.workflow_runs) ? doc.workflow_runs : [];
      const run = runs.find((w) => w && w.display_title === `Run it ${requestId}`);
      return run && Number.isSafeInteger(run.id) ? run.id : null;
    },
    async run(runId, signal) {
      const run = await read(`${api}/runs/${runId}`, signal);
      let publishing = false;
      if (run.status === "in_progress") {
        const jobs = await read(`${api}/runs/${runId}/jobs?per_page=10`, signal);
        const list = Array.isArray(jobs.jobs) ? jobs.jobs : [];
        const verify = list.find((j) => j && j.name === "verify");
        publishing = Boolean(verify && verify.status === "completed" && verify.conclusion === "success");
      }
      return { status: String(run.status), conclusion: run.conclusion === null ? null : String(run.conclusion), publishing };
    },
    // The published status.json's phase, or null when it cannot be read. Used only for the breaker:
    // a run that published a failed phase counts as a failed run.
    async publishedPhase(requestId, signal) {
      try {
        const doc = await read(`https://raw.githubusercontent.com/${REPO}/run-it-results/${requestId}/status.json`, signal, false);
        return doc && typeof doc.phase === "string" ? doc.phase : null;
      } catch {
        return null;
      }
    },
  };
}

// What GitHub says about a run, in the contract's words.
export function stateOf(run) {
  if (run.status === "completed") {
    if (run.conclusion === "success") return "published";
    if (run.conclusion === "cancelled") return "cancelled";
    return "failed";
  }
  if (run.status === "in_progress") return run.publishing ? "publishing" : "running";
  return "queued";   // queued, requested, waiting, pending
}

// --- the service -----------------------------------------------------------------------------------

export function createService({ env = {}, store = memoryStore(), fetch: fetchFn = globalThis.fetch, now = Date.now,
                                newId = () => crypto.randomUUID(), log = () => {}, waitUntil = () => {} } = {}) {
  const config = readConfig(env);
  const gh = github(config.token, fetchFn);
  let chain = Promise.resolve();
  const refreshing = new Map();

  // One request at a time changes the state: everything after an await sees what the one before wrote.
  function serial(fn) {
    const next = chain.then(fn, fn);
    chain = next.catch(() => {});
    return next;
  }

  async function visitorKey(request) {
    const address = request.headers.get(config.visitorHeader) || "unknown";
    const bytes = new TextEncoder().encode(`${config.salt}:${address}`);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest).slice(0, 16), (b) => b.toString(16).padStart(2, "0")).join("");
  }

  async function breakerState() {
    const b = (await store.get("breaker")) || {};
    return b.epoch === config.breakerEpoch ? b : { epoch: config.breakerEpoch, failedInARow: 0 };
  }

  async function broken() {
    return (await breakerState()).failedInARow >= config.breaker;
  }

  async function finished(outcome) {
    // outcome: "failed", "ok", or "unknown" (neither counts nor resets).
    if (outcome === "unknown") return;
    const b = await breakerState();
    b.failedInARow = outcome === "failed" ? b.failedInARow + 1 : 0;
    await store.put("breaker", b);
    if (outcome === "failed") log(`a run failed; ${b.failedInARow} in a row`);
  }

  function statusBody(requestId, run) {
    return { format: FORMAT, kind: "status", requestId, sample: run.sample, state: run.state, updatedAt: iso(run.updatedAt), standIn: false };
  }

  // Network work stays outside the admission lock. Only the final state change is serialized.
  async function refresh(requestId, previous) {
    const original = await store.get(`run:${requestId}`);
    if (!original) return previous; // a pruned run is never resurrected by a late refresh
    const run = { ...original };
    if (!ACTIVE.has(run.state)) return run;
    const t = now();
    if (run.checkedAt && t - run.checkedAt < STATUS_TTL_MS) return run;
    run.checkedAt = t;
    let state = run.state;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(new DOMException("Status refresh deadline", "TimeoutError")), STATUS_REFRESH_MS);
    try {
      let observed = false;
      try {
        if (!run.runId) run.runId = await gh.findRun(requestId, run.dispatchedAt, controller.signal);
        if (run.runId) state = stateOf(await gh.run(run.runId, controller.signal));
        else if (t - run.dispatchedAt > LOST_AFTER_MS) state = "failed";
        observed = true;
      } catch {
        log(`status of ${requestId} could not be read`);
      }
      // Age alone is not evidence that the run failed when its status could not be read.
      if (observed && ACTIVE.has(state) && t - run.dispatchedAt > GIVE_UP_MS) state = "failed";
      if (state !== run.state) { run.state = state; run.updatedAt = t; }
      let outcome = "unknown";
      if (!ACTIVE.has(run.state)) {
        outcome = "failed";
        if (run.state === "published") {
          const phase = await gh.publishedPhase(requestId, controller.signal);
          outcome = phase === "completed" ? "ok" : phase === null ? "unknown" : "failed";
        }
      }
      return await serial(async () => {
        const current = await store.get(`run:${requestId}`);
        if (!current) return previous;
        if (current.dispatchedAt !== original.dispatchedAt || current.checkedAt !== original.checkedAt ||
            current.state !== original.state) return current;
        if (!ACTIVE.has(run.state)) {
          await finished(outcome);
          if (await store.get("active") === requestId) await store.delete("active");
        }
        await store.put(`run:${requestId}`, run);
        return run;
      });
    } finally {
      clearTimeout(timer);
    }
  }

  function refreshOnce(requestId, run) {
    if (refreshing.has(requestId)) return refreshing.get(requestId);
    if (!ACTIVE.has(run.state) || (run.checkedAt && now() - run.checkedAt < STATUS_TTL_MS)) return Promise.resolve(run);
    const task = refresh(requestId, run).catch(() => {
      log(`status of ${requestId} could not be saved`);
      return run;
    }).finally(() => refreshing.delete(requestId));
    refreshing.set(requestId, task);
    waitUntil(task);
    return task;
  }

  async function promptly(task, known) {
    let timer;
    try {
      return await Promise.race([task, new Promise(resolve => {
        timer = setTimeout(() => resolve(known), STATUS_RESPONSE_MS);
      })]);
    } finally { clearTimeout(timer); }
  }

  async function health() {
    return { format: FORMAT, kind: "health", open: config.open && !(await broken()), standIn: false };
  }

  async function status(requestId) {
    if (!ID.test(requestId)) return [404, refusal("unknown-request", "No run with this request id is known here.")];
    const run = await store.get(`run:${requestId}`);
    if (!run) return [404, refusal("unknown-request", "No run with this request id is known here.")];
    return [200, statusBody(requestId, await promptly(refreshOnce(requestId, run), run))];
  }

  async function start(raw, request) {
    let doc;
    try {
      doc = JSON.parse(raw);
    } catch {
      return [400, refusal("bad-request", 'Send {"sample": "<sample id>"} as JSON.')];
    }
    if (doc === null || typeof doc !== "object" || Array.isArray(doc) || Object.keys(doc).length !== 1 || typeof doc.sample !== "string") {
      return [400, refusal("bad-request", 'Send {"sample": "<sample id>"} as JSON, and nothing else.')];
    }
    const sample = doc.sample;
    if (!ID.test(sample) || !SAMPLES.includes(sample)) return [400, refusal("unknown-sample", "That is not one of the samples Run it offers.")];
    if (UNRECORDED.has(sample) && env.RECORDED_FIX_OPEN !== "true") {
      // Its real repair recording does not exist yet (#433): refuse before admission, so a direct
      // request cannot use up a visitor's or the day's slot on a run that can only fail.
      return [503, refusal("disabled", "That sample is not recorded yet. The other samples can be run.")];
    }
    if (!config.open) {
      const why = env.RUN_IT_OPEN === "true" ? "Run it is not set up yet." : "Run it is switched off.";
      return [503, refusal("disabled", `${why} The latest finished runs are still here.`)];
    }
    const activeId = await store.get("active");
    if (activeId) {
      const run = await store.get(`run:${activeId}`);
      if (run && ACTIVE.has(run.state)) {
        refreshOnce(activeId, run);
        return [409, refusal("busy", "Another request is still reserved or running. Try again in a minute.", null, 60)];
      }
      await store.delete("active");
    }
    const b = await breakerState();
    if (b.failedInARow >= config.breaker) {
      return [503, refusal("circuit-open", `Run it stopped starting runs after ${b.failedInARow} failed runs in a row. A person has to look before it starts again; the latest finished runs are still here.`)];
    }
    const t = now();
    if (t < ((await store.get("dispatchBackoff")) || 0)) {
      return [503, refusal("unavailable", "GitHub refused a dispatch. Wait a minute before trying again.", null, 60)];
    }
    let day = await store.get("day");
    if (!day || day.date !== today(t)) day = { date: today(t), total: 0, visitors: {} };
    const midnight = iso(nextMidnight(t));
    if (day.total >= config.dailyCap) {
      return [429, refusal("daily-cap", `Run it has started ${day.total} runs today, its most for one day. It starts again at midnight UTC.`, midnight)];
    }
    const visitor = await visitorKey(request);
    if ((day.visitors[visitor] || 0) >= config.perVisitor) {
      return [429, refusal("visitor-quota", `You have started ${config.perVisitor} runs today, the most for one visitor. Your quota resets at midnight UTC.`, midnight)];
    }
    const requestId = newId();
    if (!ID.test(requestId)) throw new Error("a minted request id is not a request id");
    const previousDay = structuredClone(day);
    day.total += 1;
    day.visitors[visitor] = (day.visitors[visitor] || 0) + 1;
    const run = { sample, state: "queued", updatedAt: t, dispatchedAt: t, runId: null, checkedAt: t };
    const recent = ((await store.get("recent")) || []).concat([requestId]);
    // Pruning can fail safely before any dispatch. Reserve all admission state atomically, so a
    // crash or lost dispatch reply cannot leave a free, untracked GitHub run.
    while (recent.length > KEEP_RUNS) await store.delete(`run:${recent.shift()}`);
    await store.putMany({ day, [`run:${requestId}`]: run, active: requestId, recent });
    try {
      await gh.dispatch(sample, requestId);
    } catch (e) {
      // Never log provider exception text: it can contain request headers or credentials.
      log("dispatch did not confirm success");
      if (e.refused) {
        await store.putMany({ day: previousDay, active: null,
          [`run:${requestId}`]: { ...run, state: "failed" }, dispatchBackoff: t + 60_000 });
        return [502, refusal("unavailable", "GitHub refused the dispatch. No run was started or counted. Wait a minute before trying again.", null, 60)];
      }
      // A timeout, lost reply or server error may follow a successful dispatch. Keep the reservation
      // and return its id for polling. Never retry POST; refresh reconciles by that same id.
    }
    return [202, { format: FORMAT, kind: "accepted", requestId, sample }];
  }

  function cors(request, headers) {
    const origin = request.headers.get("Origin");
    if (origin && config.origins.includes(origin)) {
      headers["Access-Control-Allow-Origin"] = origin;
      headers.Vary = "Origin";
    }
    return headers;
  }

  function reply(request, code, doc) {
    const headers = cors(request, { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    if (doc.retryAfterSeconds) headers["Retry-After"] = String(doc.retryAfterSeconds);
    return new Response(JSON.stringify(doc) + "\n", { status: code, headers });
  }

  async function readBody(request) {
    const declared = Number(request.headers.get("Content-Length"));
    if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) return null;
    const reader = request.body?.getReader();
    if (!reader) return "";
    const chunks = [];
    let size = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_BODY_BYTES) { await reader.cancel(); return null; }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    const buf = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { buf.set(chunk, offset); offset += chunk.byteLength; }
    try {
      return new TextDecoder("utf-8", { fatal: true }).decode(buf);
    } catch {
      return "";
    }
  }

  async function handle(request) {
    const url = new URL(request.url);
    const path = url.pathname.startsWith("/api/") ? url.pathname.slice(4) : url.pathname;
    try {
      if (request.method === "OPTIONS") {
        const headers = cors(request, { "Access-Control-Allow-Methods": "GET, POST", "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "600" });
        return new Response(null, { status: 204, headers });
      }
      if (request.method === "GET" && path === "/health") return reply(request, 200, await serial(health));
      if (request.method === "GET" && path.startsWith("/status/")) {
        const [code, doc] = await status(path.slice("/status/".length));
        return reply(request, code, doc);
      }
      if (request.method === "POST" && path === "/run") {
        const origin = request.headers.get("Origin");
        if (!origin || !config.origins.includes(origin)) {
          return reply(request, 403, refusal("bad-request", "Runs are started from the Run it page on expectrail.tech."));
        }
        const raw = await readBody(request);
        if (raw === null) return reply(request, 400, refusal("bad-request", `Send a body of at most ${MAX_BODY_BYTES} bytes.`));
        const [code, doc] = await serial(() => start(raw, request));
        return reply(request, code, doc);
      }
      return reply(request, 404, refusal("bad-request", "No such endpoint."));
    } catch (e) {
      log("request failed");
      return reply(request, 500, refusal("unavailable", "Run it hit an error. A request may already be reserved; wait before trying again.", null, 60));
    }
  }

  return { handle, config };
}
