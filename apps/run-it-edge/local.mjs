// The edge function on this machine, with a pretend GitHub, for the burst script and for looking at
// it without an account (#265, slice 3). Bound to 127.0.0.1 only. Not a stand-in for real runs: the
// pretend GitHub finishes every dispatched run after --run-seconds and publishes nothing.
//
//   node apps/run-it-edge/local.mjs [--port 8787] [--run-seconds 2] [--per-visitor 3] [--daily-cap 40]
//   python3 -m tools.runit_burst http://127.0.0.1:8787 --count 50
import http from "node:http";
import { createService, memoryStore } from "./service.js";

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith("--") ? acc.concat([[a.slice(2), all[i + 1]]]) : acc), []));
const runSeconds = Number(args["run-seconds"] || 2);

const runs = new Map();
let nextId = 1;
function pretendGitHub(url, init = {}) {
  const json = (status, doc) => Promise.resolve(new Response(doc === undefined ? null : JSON.stringify(doc), { status }));
  if ((init.method || "GET") === "POST") {
    const body = JSON.parse(init.body);
    runs.set(body.inputs.request_id, { id: nextId++, at: Date.now() });
    return json(204);
  }
  const done = (r) => Date.now() - r.at > runSeconds * 1000;
  if (url.includes("/workflows/run-it.yml/runs?")) {
    return json(200, { workflow_runs: [...runs.entries()].map(([rid, r]) => ({ id: r.id, display_title: `Run it ${rid}` })) });
  }
  let m = /\/actions\/runs\/([0-9]+)(\/jobs)?/.exec(url);
  if (m) {
    const r = [...runs.values()].find((x) => x.id === Number(m[1]));
    if (m[2]) return json(200, { jobs: [{ name: "verify", status: "in_progress", conclusion: null }] });
    return json(200, { id: r.id, status: done(r) ? "completed" : "in_progress", conclusion: done(r) ? "success" : null });
  }
  if (/status\.json$/.test(url)) return json(200, { phase: "completed" });
  return json(404);
}

const service = createService({
  env: {
    GITHUB_TOKEN: "local-pretend-token-not-a-secret", VISITOR_SALT: "local-salt-".repeat(4), RUN_IT_OPEN: "true",
    PER_VISITOR: args["per-visitor"] || "3", DAILY_CAP: args["daily-cap"] || "40",
    ALLOWED_ORIGINS: "https://expectrail.tech", VISITOR_HEADER: "X-Local-Address",
  },
  store: memoryStore(),
  fetch: pretendGitHub,
});

const server = http.createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const headers = new Headers();
  for (const [k, v] of Object.entries(req.headers)) if (typeof v === "string") headers.set(k, v);
  headers.set("X-Local-Address", req.socket.remoteAddress || "unknown");   // never the client's own claim
  const body = ["GET", "HEAD", "OPTIONS"].includes(req.method) ? undefined : Buffer.concat(chunks);
  const answer = await service.handle(new Request(`http://127.0.0.1${req.url}`, { method: req.method, headers, body }));
  res.writeHead(answer.status, Object.fromEntries(answer.headers.entries()));
  res.end(Buffer.from(await answer.arrayBuffer()));
});

server.listen(Number(args.port || 8787), "127.0.0.1", () => {
  console.log(`Run it edge function, local with a pretend GitHub: http://127.0.0.1:${server.address().port}`);
});
