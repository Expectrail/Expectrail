// Verify a receipt (#265). Wires the page to receipt-check.js. Nothing is written as HTML from a
// receipt: every value goes in with textContent. The outcome shown is check()'s, and only
// "clearance" is green.
"use strict";

(function () {
  var $ = function (id) { return document.getElementById(id); };
  var R = window.ExpectrailReceipt;

  function el(tag, text) { var n = document.createElement(tag); if (text != null) n.textContent = text; return n; }
  function list(title, items) {
    var frag = document.createDocumentFragment();
    if (!items.length) return frag;
    frag.appendChild(el("h3", title));
    var ul = el("ul");
    items.forEach(function (t) { ul.appendChild(el("li", t)); });
    frag.appendChild(ul);
    return frag;
  }
  function quote(v) { return /^[A-Za-z0-9_./:=@+-]+$/.test(v) ? v : "'" + v.replace(/'/g, "'\\''") + "'"; }
  function value(id) { var v = $(id).value.trim(); return v === "" ? null : v; }

  function command() {
    var parts = ["python -m expectrail.receipt trust-check receipt.json --trust-store trust-store.json"];
    if (value("expect-repo") !== null) parts.push("--repo " + quote(value("expect-repo")));
    if (value("expect-head") !== null) parts.push("--expect-head " + quote(value("expect-head")));
    if (value("expect-build") !== null) parts.push("--expect-build " + quote(value("expect-build")));
    if (value("expect-policy") !== null) parts.push("--expect-policy " + quote(value("expect-policy")));
    return parts.join(" ");
  }

  function show(result) {
    var tone = "review", title, means;
    if (result.outcome === "clearance") {
      tone = "pass";
      title = "Clearance";
      means = "Every condition was shown: a trusted key signed this receipt, it is about the build and policy you expect, it is in date, and every required check passed on full evidence. It says what was checked; it does not say the game is correct.";
    } else if (result.outcome === "no-clearance") {
      tone = "fail";
      title = "No clearance";
      means = result.report.valid_signature ?
        "The signature is valid, but not everything needed for clearance was shown. What is missing is listed below." :
        "This receipt is not shown to come from a key you trust, so nothing in it is established.";
    } else if (result.outcome === "invalid") {
      title = "Not a receipt this page can read";
      means = (result.message || "") + ". trust-check refuses it too.";
    } else {
      title = "Cannot tell here";
      means = (result.message || "") + ". This is not a pass. Check it with trust-check (below).";
    }
    $("outcome").setAttribute("data-tone", tone);
    $("outcome-title").textContent = title;
    $("outcome-means").textContent = means;
    // What the issuer line can say without saying more than the check decided (issuer_word in receipt.py).
    function hasReason(r, start) { return r.reasons.some(function (x) { return x.indexOf(start) === 0; }); }
    function issuerText(r) {
      if (r.known_issuer) return "in your trust store";
      if (hasReason(r, "issuer key revoked at ")) return "in your trust store, and revoked";
      if (hasReason(r, "receipt issued outside the issuer key's validity")) {
        return "in your trust store, but not valid when the receipt says it was issued";
      }
      return "not in your trust store";
    }
    var details = $("details");
    details.textContent = "";
    if (result.report) {
      var r = result.report, dne = r.does_not_establish;
      var notChecked = function (a, b) { return dne.indexOf(a) !== -1 || (b && dne.indexOf(b) !== -1); };
      var facts = el("dl");
      facts.className = "facts";
      [["Signature", r.valid_signature ? "valid" : "not valid with a trusted key"],
       ["Issuer", issuerText(r)],
       ["Build identity", (notChecked("repository not checked", "head not checked") || notChecked("build not checked")) ? "not checked" :
         (r.identity_ok ? "matches" : (hasReason(r, "repository mismatch") || hasReason(r, "head digest mismatch") ||
           hasReason(r, "build digest mismatch") ? "does not match" : "not shown: no valid signature from a trusted key"))],
       ["Policy", notChecked("policy not checked") ? "not checked" : (r.policy_ok ? "matches" : "does not match")],
       ["In date", r.fresh ? "yes" : "no"],
       ["Complete", r.complete ? "yes" : "no"],
       ["Decision in the receipt", String(r.decision)]].forEach(function (f) {
        facts.appendChild(el("dt", f[0]));
        facts.appendChild(el("dd", f[1]));
      });
      details.appendChild(facts);
      details.appendChild(list("It establishes", r.establishes));
      details.appendChild(list("It does not establish", dne));
      details.appendChild(list("Reasons", r.reasons));
    }
    details.appendChild(el("h3", "The same check on your machine"));
    details.appendChild(el("pre", command()));
    $("result").hidden = false;
  }

  async function run() {
    var result = await R.check($("receipt-text").value, $("store-text").value, {
      expectRepo: value("expect-repo"), expectHead: value("expect-head"), expectBuild: value("expect-build"), expectPolicy: value("expect-policy")
    });
    show(result);
  }

  function readFile(input, target) {
    input.addEventListener("change", function () {
      var f = input.files && input.files[0];
      if (!f) return;
      if (f.size > 1024 * 1024) { $(target).value = ""; show({outcome: "invalid", message: "the file is larger than 1 MB"}); return; }
      f.text().then(function (t) { $(target).value = t; });
    });
  }

  async function sample(name) {
    try {
      var got = await Promise.all([fetch("samples/test-receipt-" + name + ".json"), fetch("samples/test-trust-store.json")]);
      if (!got[0].ok || !got[1].ok) throw new Error("the sample files did not load");
      var texts = await Promise.all([got[0].text(), got[1].text()]);
      $("receipt-text").value = texts[0];
      $("store-text").value = texts[1];
      var doc = JSON.parse(texts[0]);
      $("expect-repo").value = doc.repository || "";
      $("expect-head").value = doc.headSha256 || "";
      $("expect-build").value = doc.buildSha256 || "";
      $("expect-policy").value = doc.policySha256 || "";
      $("sample-note").textContent = "Test " + name + " loaded. It is signed by a throwaway test key whose private half was discarded: it shows the check working and proves nothing about any game. It is valid until " + doc.expiresAt + "; after that it gets no clearance, as it should.";
      $("sample-note").hidden = false;
      await run();
    } catch (e) {
      show({outcome: "cannot-tell", message: "the test sample could not be loaded (" + e.message + ")"});
    }
  }

  readFile($("receipt-file"), "receipt-text");
  readFile($("store-file"), "store-text");
  $("check").addEventListener("click", run);
  $("sample-accept").addEventListener("click", function () { sample("accept"); });
  $("sample-reject").addEventListener("click", function () { sample("reject"); });
})();
