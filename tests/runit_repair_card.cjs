// Run the shipped page script against an offline service and a latest entry for an unpublished fix.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const sampleDir = "docs/run-it/";
const manifest = JSON.parse(fs.readFileSync(sampleDir + "samples.json", "utf8"));
const script = fs.readFileSync(sampleDir + "run-it.js", "utf8");
const nodes = [];
function element() {
  const node = {
    dataset: {}, attributes: {}, children: [], textContent: "",
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener() {},
    appendChild(child) { child.parent = this; this.children.push(child); },
    closest() { return this.className === "sample" ? this : this.parent.closest(); }
  };
  nodes.push(node);
  return node;
}
const elements = Object.fromEntries(["samples", "service", "standin"].map(id => [id, element()]));
const document = {
  createElement: element, getElementById: id => elements[id],
  querySelectorAll: () => nodes.filter(n => n.attributes["data-run"]),
  querySelector(selector) {
    const [, attr, id] = selector.match(/^\[(data-[a-z]+)="([a-z-]+)"\]$/);
    return nodes.find(n => n.attributes[attr] === id);
  }
};
const requests = [];
const responses = {
  "samples.json": manifest,
  "/api/health": {format: "expectrail.run-it-api/v1", kind: "health", open: true},
  "/results/latest.json": {format: "expectrail.run-it-latest/v1", samples: {"recorded-fix": {requestId: "old", finishedAt: "2026-11-14T00:00:00Z"}}},
  "earlier/latest.json": {format: "expectrail.run-it-latest/v1", samples: {"recorded-fix": {requestId: "cached-old", finishedAt: "2026-11-13T00:00:00Z"}}}
};
async function fetch(url) {
  requests.push(url);
  return {status: 200, json: async () => responses[url]};
}
vm.runInNewContext(script, {document, fetch, location: {hostname: "localhost", hash: "#local"}});
setImmediate(() => {
  const run = document.querySelector('[data-run="recorded-fix"]');
  assert.ok(run.disabled);
  assert.equal(document.querySelector('[data-run="clean"]').disabled, false);
  assert.ok(run.closest().children.some(n => n.textContent === "fix not recorded yet"));
  assert.ok(document.querySelector('[data-show="recorded-fix"]').hidden);
  assert.deepEqual(requests.sort(), Object.keys(responses).sort());
});
