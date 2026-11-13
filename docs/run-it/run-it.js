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
  var latest = {};           // sample id -> {requestId, finishedAt}
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
    return fetch(url, { cache: "no-store", credentials: "omit", signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) {
        if (timer) clearTimeout(timer);
        return r.json().then(function (doc) { return { status: r.status, doc: doc }; },
                             function () { return { status: r.status, doc: null }; });
      }, function (e) { if (timer) clearTimeout(timer); throw e; });
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
      if (v.recorded === true && v.notRecorded === 0 && v.answered > 0 && v.answered === v.asked) {
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

  // status.json, read defensively: anything off means "cannot tell", never a verdict.
  function usable(status, requestId, sampleId) {
    if (!isObj(status) || status.format !== "expectrail.run-it-result/v1") return false;
    if (status.requestId !== requestId || !isObj(status.sample) || status.sample.id !== sampleId) return false;
    if (["completed", "failed", "cancelled"].indexOf(status.phase) === -1) return false;
    if (["accept", "reject", "needs-review", null].indexOf(status.decision) === -1) return false;
    if (!isObj(status.vision) || !isObj(status.receipt) || !Array.isArray(status.diagnostics)) return false;
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
      else setService("Run it is not starting runs right now. The latest finished run of each sample is below.", "no");
    }).catch(function () {
      open = false;
      setService("Run it cannot start runs right now: the service that starts them is not reachable. The latest finished run of each sample is below, when there is one.", "no");
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
      if (s.expected) li.appendChild(el("p", "A working install decides: " + s.expected + ".", "expect"));
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
      show.addEventListener("click", function () { showLatest(s.id, "This is the most recent finished run of this sample."); });
      actions.appendChild(show);
      li.appendChild(actions);
      list.appendChild(li);
    });
    renderButtons();
  }

  function renderButtons() {
    var buttons = document.querySelectorAll("button[data-run]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].disabled = !open || busy;
      buttons[i].title = !open ? "Run it is not starting runs right now" : (busy ? "Your run is going" : "");
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
        if (ID.test(id) && isObj(row) && typeof row.requestId === "string" && ID.test(row.requestId)) latest[id] = row;
      });
    }).catch(function () { latest = {}; }).then(renderLatest);
  }

  function renderLatest() {
    samples.forEach(function (s) {
      var line = document.querySelector('[data-latest="' + s.id + '"]');
      var show = document.querySelector('[data-show="' + s.id + '"]');
      if (!line || !show) return;
      var row = latest[s.id];
      if (!row) { line.textContent = "No finished run of this sample yet."; show.hidden = true; return; }
      line.textContent = "Latest run: " + when(row.finishedAt) + ".";
      show.hidden = false;
      getJson(RESULTS + "/" + row.requestId + "/status.json").then(function (res) {
        if (res.status === 200 && usable(res.doc, row.requestId, s.id)) {
          line.textContent = "Latest run, " + when(row.finishedAt) + ": " + decisionWord(res.doc) + ".";
        }
      }).catch(function () {});
    });
  }

  // ---- one run --------------------------------------------------------------------------------
  function openPanel(label, title, message) {
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

  function finish() { busy = false; renderButtons(); }

  function startRun(sampleId) {
    var s = sampleById(sampleId);
    if (!s || busy || !open) return;
    busy = true;
    renderButtons();
    openPanel("Your run", s.title, "Asking Run it to start…");
    fetch(API + "/run", {
      method: "POST", cache: "no-store", credentials: "omit",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sample: sampleId })
    }).then(function (r) {
      return r.json().then(function (doc) { return { status: r.status, doc: doc }; }, function () { return { status: r.status, doc: null }; });
    }).then(function (res) {
      var doc = res.doc;
      if (isObj(doc) && doc.format === API_FORMAT && doc.kind === "accepted" && typeof doc.requestId === "string"
          && ID.test(doc.requestId) && doc.sample === sampleId) {
        $("run-message").textContent = "Started. This page follows the run; you can leave it open.";
        setPhase("queued");
        follow(doc.requestId, sampleId, Date.now(), 0);
        return;
      }
      finish();
      if (isObj(doc) && doc.format === API_FORMAT && doc.kind === "refused") return refused(doc, sampleId);
      $("run-message").textContent = "Run it answered in a way this page does not understand. No run was started.";
    }).catch(function () {
      finish();
      $("run-message").textContent = "Could not reach Run it. No run was started.";
    });
  }

  function refused(doc, sampleId) {
    var reset = doc.resetsAt ? " It resets at " + when(doc.resetsAt) + "." : "";
    var lead = {
      "busy": "Busy: another visitor's run is going. Try again in a minute.",
      "visitor-quota": "Today's quota is spent.",
      "daily-cap": "Run it has started its most runs for today.",
      "circuit-open": "Run it stopped starting runs after several failed runs in a row. A person has to look first.",
      "disabled": "Run it is switched off right now.",
      "unknown-sample": "That is not one of the samples Run it offers.",
      "bad-request": "Run it did not accept the request."
    }[doc.reason] || "Run it refused the request.";
    var message = lead + reset;
    if (typeof doc.detail === "string" && doc.detail) message += " (" + doc.detail + ")";
    if (doc.reason === "circuit-open" || doc.reason === "disabled") { open = false; checkService(); }
    if (latest[sampleId]) {
      showLatest(sampleId, message + " Here is the most recent finished run of this sample instead.");
    } else {
      $("run-message").textContent = message + " No earlier run of this sample is published yet.";
    }
  }

  function follow(requestId, sampleId, startedMs, misses) {
    if (Date.now() - startedMs > GIVE_UP_MS) {
      finish();
      $("run-message").textContent = "No answer from this run after 25 minutes; it may have stalled. No verdict.";
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
          setPhase(doc.state);
          return follow(requestId, sampleId, startedMs, 0);
        }
        finish();
        if (doc.state === "published") {
          $("phases").hidden = true;
          $("run-message").textContent = "Finished at " + when(doc.updatedAt) + ".";
          loadResult(requestId, sampleId);
          loadLatest();
        } else if (doc.state === "cancelled") {
          $("run-message").textContent = "Cancelled: no verdict. Nothing was published.";
        } else {
          $("run-message").textContent = "The run failed: no verdict. Nothing was published.";
        }
      }).catch(function () {
        if (misses >= 5) {
          finish();
          $("run-message").textContent = "Lost contact with Run it. The run may still finish; it will be listed here as this sample's latest run. No verdict is shown.";
          return;
        }
        follow(requestId, sampleId, startedMs, misses + 1);
      });
    }, POLL_MS);
  }

  function showLatest(sampleId, message) {
    var s = sampleById(sampleId);
    var row = latest[sampleId];
    if (!s || !row) return;
    openPanel("Earlier run, from " + when(row.finishedAt), s.title, message);
    loadResult(row.requestId, sampleId);
  }

  function fact(list, term, text, href) {
    list.appendChild(el("dt", term));
    var dd = el("dd");
    if (href) { var a = el("a", text); a.href = href; a.rel = "noopener noreferrer"; dd.appendChild(a); }
    else dd.textContent = text;
    list.appendChild(dd);
  }

  function loadResult(requestId, sampleId) {
    if (!ID.test(requestId) || !ID.test(sampleId)) return;
    var base = RESULTS + "/" + requestId + "/";
    getJson(base + "status.json").then(function (res) {
      if (res.status !== 200 || !usable(res.doc, requestId, sampleId)) throw new Error("unusable");
      showResult(res.doc, base);
    }).catch(function () {
      $("result").hidden = false;
      var box = $("verdict");
      box.setAttribute("data-tone", "review");
      $("verdict-title").textContent = "Cannot tell";
      $("verdict-means").textContent = "The published result could not be read, so no verdict is shown.";
      clear($("facts"));
      clear($("evidence-links"));
      $("diagnostics").hidden = true;
    });
  }

  function showResult(status, base) {
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
    var expected = status.sample.expected;
    fact(facts, "This sample", "A working install decides " + expected + ". This run " +
      (status.asExpected ? "ended as this sample is expected to end today." : "did not end as this sample is expected to end today."));
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
    fetch(base + "viewer/evidence.html", { cache: "no-store", credentials: "omit" }).then(function (r) {
      if (!r.ok) throw new Error("missing");
      return r.text();
    }).then(function (html) {
      if (html.length > MAX_EVIDENCE_CHARS) throw new Error("too large");
      var frame = $("viewer");
      frame.srcdoc = html;
      frame.hidden = false;
      blobUrl = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      var dl = link("Download the evidence (one file)", blobUrl);
      dl.download = "expectrail-evidence-" + status.requestId + ".html";
    }).catch(function () {
      note.textContent = "The evidence viewer could not be loaded. The verdict above is the published status.json's.";
      note.hidden = false;
    });
  }

  loadSamples().then(function () { return Promise.all([checkService(), loadLatest()]); });
})();
