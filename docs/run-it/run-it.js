// Run it (#265, slice 2). The page asks the Run it service to start a run of one sample, follows
// its state, and shows the run's published folder: status.json for what the verifier decided and the
// evidence viewer's one-file export in a sandboxed frame.
//
// Rules this file keeps:
// - The verdict shown is status.json's decision, and only an accept backed by recorded vision answers
//   is shown as accepted (green). A failed, cancelled, unreadable or empty result is never success.
// - Nothing from the service or a result is written as HTML: text goes in with textContent.
// - The only things built into a URL are ids that match ^[a-z0-9-]{1,40}$.
// - Earlier runs are always labelled earlier, with their time.
"use strict";

(function () {
  var LOOPBACK = ["localhost", "127.0.0.1", "[::1]", "::1"];
  // The local stub (tools/runit_stub.py) opens the page as /run-it/#local on 127.0.0.1. Only then are
  // the service and the results the stub's own; anywhere else, including a plain local copy of docs/,
  // they are the edge function and the run-it-results branch. The fragment can switch to the page's
  // own origin on loopback only, never to another address.
  var LOCAL = LOOPBACK.indexOf(location.hostname) !== -1 && location.hash === "#local";
  var API = LOCAL ? "/api" : "https://api.expectrail.tech";
  var RESULTS = LOCAL ? "/results" : "https://raw.githubusercontent.com/Expectrail/Expectrail/run-it-results";
  var API_FORMAT = "expectrail.run-it-api/v1";
  var ID = /^[a-z0-9-]{1,40}$/;
  var POLL_MS = 3000;
  var GIVE_UP_MS = 25 * 60 * 1000;
  var MAX_EVIDENCE_CHARS = 48 * 1024 * 1024;
  var PHASES = ["queued", "running", "publishing"];

  var samples = [];          // from samples.json
  var cachedLatest = {};     // committed earlier results; never described as a new run
  var viewSerial = 0;
  var latest = {};           // sample id -> {requestId, finishedAt}
  var publishedHere = {};    // completed runs whose status.json this visitor has read
  var open = false;
  var busy = false;          // a run of ours is going
  var blobUrl = null;

  function $(id) { return document.getElementById(id); }
  function el(tag, text, cls) {
    var node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function isObj(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }
  function when(stamp) {
    // "2026-11-20T15:05:47Z" -> "2026-11-20 15:05 UTC"; anything else is shown as it stands.
    var m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}):\d{2}Z$/.exec(String(stamp));
    return m ? m[1] + " " + m[2] + " UTC" : String(stamp);
  }
  function sampleById(id) {
    for (var i = 0; i < samples.length; i++) if (samples[i].id === id) return samples[i];
    return null;
  }

  function getJson(url, timeoutMs) {
    var ctrl = typeof AbortController === "function" ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, timeoutMs || 10000) : null;
    // Keep the timeout until the body has been read too, not merely until headers arrive.
    return fetch(url, { cache: "no-store", credentials: "omit", signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) {
        return r.json().then(function (doc) { return { status: r.status, doc: doc }; },
                             function () { return { status: r.status, doc: null }; });
      }).then(function (res) { if (timer) clearTimeout(timer); return res; },
              function (e) { if (timer) clearTimeout(timer); throw e; });
  }

  function baseFor(row) { return row.cached ? "earlier/" + row.requestId + "/" : RESULTS + "/" + row.requestId + "/"; }
  function validTime(value) { return typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value); }
  function loadCachedLatest() {
    return getJson("earlier/latest.json").then(function (res) {
      var doc = res.doc;
      if (res.status !== 200 || !isObj(doc) || doc.format !== "expectrail.run-it-latest/v1" || !isObj(doc.samples)) throw new Error("no saved index");
      Object.keys(doc.samples).forEach(function (id) {
        var row = doc.samples[id];
        if (sampleById(id) && isObj(row) && typeof row.requestId === "string" && ID.test(row.requestId) && validTime(row.finishedAt))
          cachedLatest[id] = {requestId: row.requestId, finishedAt: row.finishedAt, cached: true};
      });
    }).catch(function () { cachedLatest = {}; }).then(renderLatest);
  }

  // What a verdict looks like. Only this function decides the tone, and only one path is green.
  function verdictOf(status) {
    var v = status.vision;
    if (status.phase === "cancelled") {
      return { tone: "review", title: "Cancelled: no verdict", means: "The run was cancelled before the verifier decided." };
    }
    if (status.phase !== "completed" || status.decision === null) {
      return { tone: "review", title: "The run failed: no verdict", means: "The run did not finish, so the verifier decided nothing. It is not a pass." };
    }
    if (status.decision === "reject") {
      return { tone: "fail", title: "Rejected", means: "A check fails with this change." };
    }
    if (status.decision === "needs-review") {
      return { tone: "review", title: "Needs review", means: "Expectrail could not decide, so nothing was accepted. The reasons are in the evidence below." };
    }
    if (status.decision === "accept") {
      if (v.recorded === true && v.notRecorded === 0 && Number.isSafeInteger(v.asked) && Number.isSafeInteger(v.answered) && v.answered > 0 && v.answered === v.asked) {
        return { tone: "pass", title: "Accepted", means: "Every check passed, judged by both the engine's record and the recorded vision answers. Accepted means this change passed these checks on this route, not that the game is correct." };
      }
      return { tone: "review", title: "Needs review", means: "The result says accept, but this page cannot confirm the recorded vision answers behind it, so it does not show an accept." };
    }
    return { tone: "review", title: "Cannot tell", means: "The result's decision is not one this page knows. No verdict is shown." };
  }

  function decisionWord(status) {
    var v = verdictOf(status);
    return v.title;
  }

  // The rendering environment the frames were drawn in, beside the recording's (#265, #515). It is
  // provenance only: it never changes the verdict. The words are expectrail.recorded.rendering_sentence's,
  // and tools/runit_smoke.py holds the two to the same text. Anything malformed shows no line.
  var ENV_KEYS = ["name", "version", "renderer", "device"];
  function envOk(e, nullable) {
    if (e === null) return nullable;
    if (!isObj(e) || Object.keys(e).length !== 4) return false;
    return ENV_KEYS.every(function (k) {
      return e[k] === null || (typeof e[k] === "string" && /^[ -~]{1,160}$/.test(e[k]));
    });
  }
  function shortEnv(e) {
    return (e.device || "unknown device") + ", " + (e.renderer || "unknown renderer") + ", " +
      (e.name || "engine") + " " + (e.version || "unknown version");
  }
  function renderingLine(r) {
    if (!isObj(r) || !Array.isArray(r.thisRun) || r.thisRun.length > 8 ||
        !r.thisRun.every(function (e) { return envOk(e, false); })) return null;
    if (r.recording !== null && !(Array.isArray(r.recording) && r.recording.length <= 8 &&
        r.recording.every(function (e) { return envOk(e, true); }))) return null;
    var thisRun = r.thisRun.map(shortEnv).join(" and ");
    if (r.status === "match") return "Drawn with " + thisRun + ": the same as the recording.";
    if (r.status === "mismatch") {
      if (r.recording === null || r.recording.indexOf(null) !== -1) return null;
      return "Drawn with " + thisRun + ". The recording was made with " + r.recording.map(shortEnv).join(" and ") +
        ". A frame that draws differently gets no recorded answer.";
    }
    if (r.status === "unknown" && thisRun) return "Drawn with " + thisRun + ". The recording does not name the " +
      "environment it was made in, so the two cannot be compared. A frame that draws differently gets no recorded answer.";
    if (r.status === "unknown") return "Neither this run nor the recording names its rendering environment, so the two cannot be compared.";
    if (r.status === "unavailable") return "This run's rendering environment was not reported, so it cannot be compared with the recording's.";
    return null;
  }

  // status.json, read defensively: anything off means "cannot tell", never a verdict.
  function usable(status, requestId, sampleId) {
    if (!isObj(status) || status.format !== "expectrail.run-it-result/v1") return false;
    if (status.requestId !== requestId || !isObj(status.sample) || status.sample.id !== sampleId) return false;
    if (["completed", "failed", "cancelled"].indexOf(status.phase) === -1) return false;
    if (["accept", "reject", "needs-review", null].indexOf(status.decision) === -1) return false;
    if (!isObj(status.vision) || !isObj(status.receipt) || status.receipt.signed !== false || typeof status.receipt.why !== "string" || !Array.isArray(status.diagnostics)) return false;
    var vision = status.vision;
    if (typeof vision.recorded !== "boolean" || !Number.isSafeInteger(vision.asked) || vision.asked < 0 ||
        !Number.isSafeInteger(vision.answered) || vision.answered < 0 || vision.answered > vision.asked ||
        !Number.isSafeInteger(vision.notRecorded) || vision.notRecorded < 0 || vision.notRecorded > vision.asked) return false;
    return true;
  }

  // ---- the service ----------------------------------------------------------------------------
  function setService(text, state) {
    var node = $("service");
    node.textContent = text;
    node.setAttribute("data-open", state);
  }

  function checkService() {
    return getJson(API + "/health", 6000).then(function (res) {
      var doc = res.doc;
      if (res.status !== 200 || !isObj(doc) || doc.format !== API_FORMAT || doc.kind !== "health") throw new Error("bad health");
      $("standin").hidden = doc.standIn !== true;
      open = doc.open === true;
      if (open) setService("Run it is open. One run at a time, for every visitor; a run takes a few minutes.", "yes");
      else setService("Run it is not starting runs right now. Earlier recorded results remain available below.", "no");
    }).catch(function () {
      open = false;
      setService("Run it cannot start runs right now: the service that starts them is not reachable. Earlier recorded evidence is available below; it is not a new verification.", "no");
    }).then(renderButtons);
  }

  // ---- the samples ----------------------------------------------------------------------------
  function loadSamples() {
    return getJson("samples.json").then(function (res) {
      var doc = res.doc;
      if (res.status !== 200 || !isObj(doc) || doc.format !== "expectrail.run-it-samples/v1" || !Array.isArray(doc.samples)) throw new Error("bad manifest");
      samples = doc.samples.filter(function (s) {
        return isObj(s) && typeof s.id === "string" && ID.test(s.id) && typeof s.title === "string";
      });
      renderSamples();
    }).catch(function () {
      var list = $("samples");
      clear(list);
      list.appendChild(el("li", "The list of samples could not be loaded. Reload the page to try again.", "sample"));
    });
  }

  function renderSamples() {
    var list = $("samples");
    clear(list);
    samples.forEach(function (s) {
      var li = el("li", null, "sample");
      li.setAttribute("data-sample", s.id);
      li.appendChild(el("h3", s.title));
      li.appendChild(el("p", s.summary || ""));
      if (s.head === "recorded-fix") {
        li.id = "recorded-fix";
        // Only a published recording can enable this card. No fixture or predicted verdict.
        var availability = el("p", "Checking for a recorded fix…", "expect");
        li.appendChild(availability);
        // samples.json says whether a repair has been recorded; until then nothing is requested.
        if (s.repairRecorded !== true) {
          availability.textContent = "fix not recorded yet";
        } else getJson("repair/repair-run.json").then(function (r) {
          var d = r.doc;
          if (r.status === 404) {
            availability.textContent = "fix not recorded yet";
          } else if (r.status === 200 && isObj(d) && d.format === "expectrail.repair-run/v1"
                     && isObj(d.fixer) && d.fixer.sandboxed === true
                     && ["muse", "claude", "codex", "aider", "llm-patch"].includes(d.fixer.source)
                     && isObj(d.result) && d.result.decision === "accept" && d.result.patch && d.result.job) {
            availability.textContent = "A patch was recorded. Run it to verify the change again.";
            li.dataset.available = "yes";
            renderButtons();
            renderLatest();
          } else {
            availability.textContent = "No usable recorded fix is available.";
          }
        }).catch(function () { availability.textContent = "Could not check for a recorded fix."; });
      } else if (s.expected) li.appendChild(el("p", "A working install decides: " + s.expected + ".", "expect"));
      var line = el("p", "", "latest-line");
      line.setAttribute("data-latest", s.id);
      li.appendChild(line);
      var actions = el("div", null, "actions");
      var run = el("button", "Run it");
      run.type = "button";
      run.setAttribute("data-run", s.id);
      run.setAttribute("aria-label", "Run it: " + s.title);
      run.addEventListener("click", function () { startRun(s.id); });
      actions.appendChild(run);
      var show = el("button", "Show the latest run", "quiet");
      show.type = "button";
      show.hidden = true;
      show.setAttribute("data-show", s.id);
      show.addEventListener("click", function () { showLatest(s.id, "This is an earlier recorded result, not a new verification."); });
      actions.appendChild(show);
      li.appendChild(actions);
      list.appendChild(li);
    });
    renderButtons();
  }

  function renderButtons() {
    var buttons = document.querySelectorAll("button[data-run]");
    for (var i = 0; i < buttons.length; i++) {
      var card = buttons[i].closest(".sample");
      var missing = card.id === "recorded-fix" && card.dataset.available !== "yes";
      buttons[i].disabled = !open || busy || missing;
      buttons[i].title = missing ? "No recorded fix is available to replay" : !open ? "Run it is not starting runs right now" : (busy ? "Your run is going" : "");
    }
  }

  // ---- the latest run of each sample ----------------------------------------------------------
  function loadLatest() {
    return getJson(RESULTS + "/latest.json").then(function (res) {
      var doc = res.doc;
      if (res.status !== 200 || !isObj(doc) || doc.format !== "expectrail.run-it-latest/v1" || !isObj(doc.samples)) throw new Error("no index");
      latest = {};
      Object.keys(doc.samples).forEach(function (id) {
        var row = doc.samples[id];
        if (ID.test(id) && isObj(row) && typeof row.requestId === "string" && ID.test(row.requestId) && validTime(row.finishedAt)) latest[id] = {requestId: row.requestId, finishedAt: row.finishedAt};
      });
    }).catch(function () { latest = {}; }).then(renderLatest);
  }

  function latestRun(sampleId) {
    var indexed = latest[sampleId], saved = cachedLatest[sampleId], seen = publishedHere[sampleId];
    if (!indexed || (saved && saved.finishedAt > indexed.finishedAt)) indexed = saved;
    // The card index is fetched independently of the visitor's published result.
    if (!indexed || (seen && seen.finishedAt > indexed.finishedAt)) return seen;
    return indexed;
  }

  function renderLatest() {
    samples.forEach(function (s) {
      var line = document.querySelector('[data-latest="' + s.id + '"]');
      var show = document.querySelector('[data-show="' + s.id + '"]');
      if (!line || !show) return;
      var row = latestRun(s.id);
      var card = show.closest(".sample");
      if (s.head === "recorded-fix" && card.dataset.available !== "yes") {
        line.textContent = ""; show.hidden = true; return;
      }
      if (!row) { line.textContent = "No finished run of this sample yet."; show.hidden = true; return; }
      var label = row.cached ? "Earlier saved run" : "Latest run";
      line.textContent = label + ": " + when(row.finishedAt) + ".";
      show.textContent = row.cached ? "Show saved earlier run" : "Show the latest run";
      show.hidden = false;
      getJson(baseFor(row) + "status.json").then(function (res) {
        if (res.status === 200 && usable(res.doc, row.requestId, s.id)) {
          var current = latestRun(s.id);
          if (!current || current.requestId !== row.requestId || Boolean(current.cached) !== Boolean(row.cached)) return;
          line.textContent = label + ", " + when(row.finishedAt) + ": " + decisionWord(res.doc) + ".";
        }
      }).catch(function () {});
    });
  }

  // ---- one run --------------------------------------------------------------------------------
  function openPanel(label, title, message) {
    viewSerial++;
    if (typeof window !== "undefined" && window.RunItReceipt) window.RunItReceipt.reset();
    $("saved-findings").hidden = true; clear($("saved-findings"));
    var panel = $("run");
    panel.hidden = false;
    $("run-when").textContent = label;
    $("run-title").textContent = title;
    $("run-message").textContent = message || "";
    $("phases").hidden = true;
    $("result").hidden = true;
    $("viewer").hidden = true;
    $("viewer").removeAttribute("srcdoc");
    $("evidence-note").hidden = true;
    if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = null; }
    panel.focus({ preventScroll: true });
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function setPhase(state) {
    var at = PHASES.indexOf(state);
    var items = $("phases").querySelectorAll("li");
    for (var i = 0; i < items.length; i++) {
      var n = PHASES.indexOf(items[i].getAttribute("data-phase"));
      items[i].setAttribute("data-at", n < at ? "done" : (n === at ? "now" : "later"));
    }
    $("phases").hidden = false;
  }

  function runMessage(serial, message) {
    if (serial === viewSerial) $("run-message").textContent = message;
  }

  function finish() { busy = false; renderButtons(); }

  function startRun(sampleId) {
    var s = sampleById(sampleId);
    if (!s || busy || !open) return;
    busy = true;
    renderButtons();
    openPanel("Your run", s.title, "Asking Run it to start…");
    // Polling continues if the visitor opens an earlier result. Only the panel that
    // started this request may show its progress or verdict.
    var serial = viewSerial;
    fetch(API + "/run", {
      method: "POST", cache: "no-store", credentials: "omit",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sample: sampleId })
    }).then(function (r) {
      return r.json().then(function (doc) { return { status: r.status, doc: doc }; }, function () { return { status: r.status, doc: null }; });
    }).then(function (res) {
      var doc = res.doc;
      if (isObj(doc) && doc.format === API_FORMAT && doc.kind === "accepted" && typeof doc.requestId === "string"
          && ID.test(doc.requestId) && doc.sample === sampleId) {
        if (serial === viewSerial) {
          $("run-message").textContent = "Request reserved. Waiting for GitHub; this page follows its progress.";
          setPhase("queued");
        }
        follow(doc.requestId, sampleId, Date.now(), 0, serial);
        return;
      }
      finish();
      if (isObj(doc) && doc.format === API_FORMAT && doc.kind === "refused") return refused(doc, sampleId, serial);
      runMessage(serial, "Run it answered in a way this page does not understand. A run may already have started; wait before trying again.");
    }).catch(function () {
      finish();
      runMessage(serial, "Could not confirm the request with Run it. A run may already have started; wait before trying again.");
    });
  }

  function refused(doc, sampleId, serial) {
    var reset = doc.resetsAt ? " It resets at " + when(doc.resetsAt) + "." : "";
    var lead = {
      "busy": "Busy: another visitor's run is going. Try again in a minute.",
      "visitor-quota": "Today's quota is spent.",
      "daily-cap": "Run it has started its most runs for today.",
      "circuit-open": "Run it stopped starting runs after several failed runs in a row. A person has to look first.",
      "disabled": "Run it is switched off right now.",
      "unavailable": "Run it could not confirm the request. Wait before trying again.",
      "unknown-sample": "That is not one of the samples Run it offers.",
      "bad-request": "Run it did not accept the request."
    }[doc.reason] || "Run it refused the request.";
    var message = lead + reset;
    if (typeof doc.detail === "string" && doc.detail) message += " (" + doc.detail + ")";
    if (doc.reason === "circuit-open" || doc.reason === "disabled") { open = false; checkService(); }
    if (serial !== viewSerial) return;
    if (latestRun(sampleId)) {
      showLatest(sampleId, message + (latestRun(sampleId).cached ? " Here is a saved earlier result instead." : " Here is the most recent finished run of this sample instead."));
    } else {
      $("run-message").textContent = message + " No earlier run of this sample is published yet.";
    }
  }

  function follow(requestId, sampleId, startedMs, misses, serial) {
    if (Date.now() - startedMs > GIVE_UP_MS) {
      finish();
      runMessage(serial, "No answer from this run after 25 minutes; it may have stalled. No verdict.");
      return;
    }
    setTimeout(function () {
      getJson(API + "/status/" + requestId, 8000).then(function (res) {
        var doc = res.doc;
        if (!(isObj(doc) && doc.format === API_FORMAT && doc.kind === "status" && doc.requestId === requestId && doc.sample === sampleId)) {
          throw new Error("bad status");
        }
        if (doc.standIn === true) $("standin").hidden = false;
        if (PHASES.indexOf(doc.state) !== -1) {
          if (serial === viewSerial) setPhase(doc.state);
          return follow(requestId, sampleId, startedMs, 0, serial);
        }
        finish();
        if (doc.state === "published") {
          if (serial === viewSerial) {
            $("phases").hidden = true;
            $("run-message").textContent = "Finished at " + when(doc.updatedAt) + ".";
          }
          loadResult(requestId, sampleId, true, false, serial);
          loadLatest();
        } else {
          runMessage(serial, doc.state === "cancelled" ? "Cancelled: no verdict. Nothing was published."
                                                       : "The run failed: no verdict. Nothing was published.");
        }
      }).catch(function () {
        if (misses >= 5) {
          finish();
          runMessage(serial, "Lost contact with Run it. The run may still finish; it will be listed here as this sample's latest run. No verdict is shown.");
          return;
        }
        follow(requestId, sampleId, startedMs, misses + 1, serial);
      });
    }, POLL_MS);
  }

  function showLatest(sampleId, message) {
    var s = sampleById(sampleId);
    var row = latestRun(sampleId);
    if (!s || !row) return;
    openPanel((row.cached ? "Earlier saved run, from " : "Earlier run, from ") + when(row.finishedAt), s.title, message);
    loadResult(row.requestId, sampleId, false, row.cached, viewSerial);
  }

  function fact(list, term, text, href) {
    list.appendChild(el("dt", term));
    var dd = el("dd");
    if (href) { var a = el("a", text); a.href = href; a.rel = "noopener noreferrer"; dd.appendChild(a); }
    else dd.textContent = text;
    list.appendChild(dd);
  }

  function savedFindingsUsable(doc, status) {
    if (!isObj(doc) || doc.format !== "expectrail.findings/v0" || doc.decision !== status.decision ||
        !Array.isArray(doc.reasons) || !Array.isArray(doc.checks) || !doc.checks.length || !isObj(doc.counts) || !isObj(doc.observers) || doc.observers.rule !== "both") return false;
    var counts = {pass: 0, fail: 0, "needs-review": 0};
    for (var i = 0; i < doc.checks.length; i++) {
      var row = doc.checks[i];
      if (!isObj(row) || typeof row.spec !== "string" || typeof row.route !== "string" || !Object.prototype.hasOwnProperty.call(counts, row.after)) return false;
      var measured = isObj(row.observed) && isObj(row.observed.after) ? row.observed.after : {};
      if (row.after === "pass" && (measured.engine !== "pass" || measured.visual !== "pass")) return false;
      if (row.after === "fail" && measured.engine !== "fail" && measured.visual !== "fail") return false;
      counts[row.after]++;
    }
    if (doc.counts.checks !== doc.checks.length || doc.counts.passed !== counts.pass || doc.counts.failed !== counts.fail || doc.counts.needsReview !== counts["needs-review"]) return false;
    if (status.decision === "accept" && (counts.pass !== doc.checks.length || doc.drafts !== 0 || doc.checkProblems !== 0)) return false;
    if (status.decision === "reject" && counts.fail === 0) return false;
    return true;
  }

  function savedFindings(doc) {
    var container = $("saved-findings"); clear(container); container.hidden = false;
    container.appendChild(el("h3", "Saved findings from this earlier run"));
    doc.reasons.forEach(function (reason) { container.appendChild(el("p", String(reason))); });
    var table = el("table", null, "saved-checks");
    var header = el("tr");
    ["Check", "Route", "Head", "Base", "Engine", "Recorded vision"].forEach(function (name) { header.appendChild(el("th", name)); });
    table.appendChild(header);
    doc.checks.forEach(function (row) {
      var line = el("tr"), observed = isObj(row.observed) && isObj(row.observed.after) ? row.observed.after : {};
      [row.spec, row.route, row.after, row.before || "not compared", observed.engine || "not recorded", observed.visual || "not recorded"].forEach(function (text) { line.appendChild(el("td", String(text))); });
      table.appendChild(line);
    });
    container.appendChild(table);
  }

  function loadResult(requestId, sampleId, justPublished, cached, serial) {
    if (!ID.test(requestId) || !ID.test(sampleId)) return;
    var base = baseFor({requestId: requestId, cached: cached});
    getJson(base + "status.json").then(function (res) {
      if (res.status !== 200 || !usable(res.doc, requestId, sampleId)) throw new Error("unusable");
      var status = res.doc;
      if (cached) return getJson(base + "findings.json").then(function (findings) {
        if (findings.status !== 200 || !savedFindingsUsable(findings.doc, status)) throw new Error("unusable saved findings");
        if (serial !== viewSerial) return;
        showResult(status, base, findings.doc);
      });
      if (justPublished && typeof status.finishedAt === "string") {
        publishedHere[sampleId] = {requestId: requestId, finishedAt: status.finishedAt};
        renderLatest();
      }
      if (serial !== viewSerial) return;
      showResult(status, base);
    }).catch(function () {
      if (serial !== viewSerial) return;
      $("result").hidden = false;
      $("verdict").setAttribute("data-tone", "review");
      $("verdict-title").textContent = "Cannot tell";
      $("verdict-means").textContent = "The published result could not be read consistently, so no verdict is shown. The saved earlier evidence links remain available.";
      clear($("facts")); clear($("evidence-links")); $("diagnostics").hidden = true;
    });
  }

  function showResult(status, base, saved) {
    var serial = viewSerial;
    if (typeof window !== "undefined" && window.RunItReceipt) window.RunItReceipt.reset();
    var verdict = verdictOf(status);
    var v = status.vision;
    $("result").hidden = false;
    $("verdict").setAttribute("data-tone", verdict.tone);
    $("verdict").setAttribute("data-decision", String(status.decision));
    $("verdict-title").textContent = verdict.title;
    $("verdict-means").textContent = verdict.means;

    var facts = $("facts");
    clear(facts);
    var vision;
    if (v.recorded === true) {
      vision = "Vision answers recorded on " + v.recordedAt + " (" + (v.model || "model not named") + ", recording run " + v.run + "): "
        + v.answered + " of " + v.asked + " questions answered from the recording.";
      if (v.notRecorded) vision += " " + v.notRecorded + " had no recorded answer, so they were not answered.";
      if (v.why) vision += " " + v.why;
    } else if (v.why) {
      vision = "No recorded vision answers were used, so the vision observer gave no answer: " + String(v.why).replace(/\.$/, "") + ".";
    } else {
      vision = "No vision answers are recorded for this sample yet, so the vision observer gave no answer.";
    }
    fact(facts, "Vision", vision);
    var rendering = renderingLine(v.rendering);
    if (rendering) fact(facts, "Rendering", rendering);
    var expectation = "A working install decides " + status.sample.expected + ". ";
    if (status.phase === "completed" && status.decision === "accept" && verdict.tone === "review") {
      expectation += "The gate recorded accept. Run it needs review because the recorded vision answers are incomplete.";
    } else {
      expectation += "This run " + (status.asExpected ? "ended" : "did not end") + " as this sample is expected to end today.";
    }
    fact(facts, "This sample", expectation);
    fact(facts, "Receipt", status.receipt.why || "not signed");
    fact(facts, "Ran", when(status.startedAt) + " to " + when(status.finishedAt));
    if (typeof status.expectrailCommit === "string" && /^[0-9a-f]{40}$/.test(status.expectrailCommit)) {
      fact(facts, "Expectrail", "commit " + status.expectrailCommit.slice(0, 12),
           "https://github.com/Expectrail/Expectrail/commit/" + status.expectrailCommit);
    }
    fact(facts, "Request", status.requestId);

    var diag = $("diagnostics");
    clear(diag);
    status.diagnostics.slice(0, 20).forEach(function (d) {
      if (!isObj(d)) return;
      var li = el("li");
      li.appendChild(el("code", String(d.code)));
      li.appendChild(document.createTextNode(": " + String(d.detail)));
      diag.appendChild(li);
    });
    diag.hidden = !diag.firstChild;

    var links = $("evidence-links");
    clear(links);
    function link(text, href) { var a = el("a", text); a.href = href; a.rel = "noopener noreferrer"; links.appendChild(a); return a; }
    link("status.json", base + "status.json");
    if (status.findings === "findings.json") link("findings.json", base + "findings.json");

    var note = $("evidence-note");
    if (saved) {
      savedFindings(saved);
      note.textContent = "This is a saved earlier result, not a new verification. Full frames are not cached here; the original published viewer is linked separately.";
      note.hidden = false;
      link("Original published viewer", RESULTS + "/" + status.requestId + "/viewer/evidence.html");
      return;
    }
    fetch(base + "viewer/evidence.html", { cache: "no-store", credentials: "omit" }).then(function (r) {
      if (!r.ok) throw new Error("missing");
      return r.text();
    }).then(function (html) {
      if (serial !== viewSerial) return;
      if (html.length > MAX_EVIDENCE_CHARS) throw new Error("too large");
      var frame = $("viewer");
      frame.srcdoc = html;
      frame.hidden = false;
      blobUrl = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      var dl = link("Download the evidence (one file)", blobUrl);
      dl.download = "expectrail-evidence-" + status.requestId + ".html";
    }).catch(function () {
      if (serial !== viewSerial) return;
      note.textContent = "The evidence viewer could not be loaded. The verdict above is the published status.json's.";
      note.hidden = false;
    });
  }

  loadSamples().then(function () { return Promise.all([loadCachedLatest(), checkService(), loadLatest()]); });
})();
