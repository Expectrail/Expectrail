// Receipt check in the browser (#265: "verify a receipt"). The same allow-list as
// `python -m expectrail.receipt trust-check` (expectrail/receipt.py), run on the visitor's machine.
// Nothing is sent anywhere: the page's policy has connect-src 'self', which only lets it fetch its two
// samples from the same site; a receipt or trust store the visitor chooses is read locally.
//
// Rules this file keeps:
// - Clearance only when every condition receipt.py requires was positively shown. Nothing missing
//   is filled in as a pass.
// - The signature is over Python's canonical JSON (sort_keys, separators (",", ":"),
//   ensure_ascii=False). This file parses the receipt with its own strict parser, keeping each
//   number's text, and rebuilds those bytes exactly: Python's key order (code points), its string
//   escapes, int against float, and float repr.
// - Where it cannot be sure it matches Python (a timestamp form outside RFC 3339, base64 that is
//   not canonical, a browser without Ed25519), the outcome is "cannot-tell", never a pass.
// - Its reports match check_receipt() field for field; tests/test_verify_receipt_page.py holds it
//   to that.
"use strict";

(function (root) {
  var FORMAT = "expectrail.receipt/v1";
  var TRUST_STORE_FORMAT = "expectrail.trust-store/v1";
  var MICROS_PER_DAY = 86400 * 1000000;
  var MAX_VALIDITY = 7 * MICROS_PER_DAY;

  function Invalid(message) { this.kind = "invalid"; this.message = message; }
  function CannotTell(message) { this.kind = "cannot-tell"; this.message = message; }

  // A JSON number as written, with the value Python would read.
  function Num(lexeme) {
    this.lexeme = lexeme;
    this.isInt = !/[.eE]/.test(lexeme);
    this.value = Number(lexeme);
  }

  // ---- strict JSON (Python's json.loads with duplicate keys and NaN/Infinity refused) ----

  function parse(text) {
    var i = 0;
    function fail(what) { throw new Invalid("not valid JSON: " + what + " at character " + i); }
    function ws() { while (i < text.length && " \t\n\r".indexOf(text[i]) !== -1) i++; }
    function value() {
      ws();
      var c = text[i];
      if (c === "{") return object();
      if (c === "[") return array();
      if (c === '"') return string();
      if (c === "t" && text.substr(i, 4) === "true") { i += 4; return true; }
      if (c === "f" && text.substr(i, 5) === "false") { i += 5; return false; }
      if (c === "n" && text.substr(i, 4) === "null") { i += 4; return null; }
      if (c === "N" || c === "I" || (c === "-" && text[i + 1] === "I")) fail("NaN and Infinity are refused");
      return number();
    }
    function object() {
      i++;
      var out = Object.create(null), seen = Object.create(null);
      ws();
      if (text[i] === "}") { i++; return out; }
      for (;;) {
        ws();
        if (text[i] !== '"') fail("expected a key");
        var key = string();
        if (seen[key]) throw new Invalid("duplicate key " + JSON.stringify(key));
        seen[key] = true;
        ws();
        if (text[i] !== ":") fail("expected ':'");
        i++;
        out[key] = value();
        ws();
        if (text[i] === ",") { i++; continue; }
        if (text[i] === "}") { i++; return out; }
        fail("expected ',' or '}'");
      }
    }
    function array() {
      i++;
      var out = [];
      ws();
      if (text[i] === "]") { i++; return out; }
      for (;;) {
        out.push(value());
        ws();
        if (text[i] === ",") { i++; continue; }
        if (text[i] === "]") { i++; return out; }
        fail("expected ',' or ']'");
      }
    }
    function string() {
      i++;
      var out = "";
      for (;;) {
        if (i >= text.length) fail("unterminated string");
        var c = text[i];
        var code = c.charCodeAt(0);
        if (c === '"') { i++; break; }
        if (code < 0x20) fail("control character in string");
        if (c === "\\") {
          var e = text[i + 1];
          var simple = {'"': '"', "\\": "\\", "/": "/", b: "\b", f: "\f", n: "\n", r: "\r", t: "\t"};
          if (e in simple) { out += simple[e]; i += 2; continue; }
          if (e === "u" && /^[0-9a-fA-F]{4}$/.test(text.substr(i + 2, 4))) {
            out += String.fromCharCode(parseInt(text.substr(i + 2, 4), 16));
            i += 6;
            continue;
          }
          fail("bad escape");
        }
        out += c;
        i++;
      }
      // Python reads a lone surrogate, then refuses to encode it (canonical_v1). Refuse it here.
      if (/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(^|[^\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(out)) {
        throw new Invalid("a string holds a lone surrogate");
      }
      return out;
    }
    function number() {
      var m = /^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?/.exec(text.slice(i));
      if (!m) fail("unexpected character");
      i += m[0].length;
      var n = new Num(m[0]);
      if (!n.isInt && !isFinite(n.value)) throw new Invalid("a number is too large to be finite");
      return n;
    }
    if (text.charCodeAt(0) === 0xFEFF) throw new Invalid("not valid JSON: a byte order mark");
    var result = value();
    ws();
    if (i !== text.length) fail("extra data");
    return result;
  }

  // ---- Python's canonical_v1 ----

  function codePoints(s) { return Array.from(s, function (ch) { return ch.codePointAt(0); }); }
  function cmpCodePoints(a, b) {
    var x = codePoints(a), y = codePoints(b);
    for (var k = 0; k < Math.min(x.length, y.length); k++) if (x[k] !== y[k]) return x[k] - y[k];
    return x.length - y.length;
  }

  function pyString(s) {
    var map = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"};
    return '"' + s.replace(/[\x00-\x1f\\"]/g, function (c) {
      return map[c] || "\\u" + ("0000" + c.charCodeAt(0).toString(16)).slice(-4);
    }) + '"';
  }

  // float.__repr__: shortest round-trip digits; fixed notation when -4 <= exponent < 16.
  function pyFloat(x) {
    if (!isFinite(x)) throw new Invalid("a number is not finite");
    if (x === 0) return Object.is(x, -0) ? "-0.0" : "0.0";
    var sign = x < 0 ? "-" : "";
    var m = /^(\d)(?:\.(\d+))?e([+-]\d+)$/.exec(Math.abs(x).toExponential());
    var digits = m[1] + (m[2] || "");
    var exp = parseInt(m[3], 10);
    var decpt = exp + 1;
    if (decpt > -4 && decpt <= 16) {
      if (decpt <= 0) return sign + "0." + "0".repeat(-decpt) + digits;
      if (decpt >= digits.length) return sign + digits + "0".repeat(decpt - digits.length) + ".0";
      return sign + digits.slice(0, decpt) + "." + digits.slice(decpt);
    }
    var e = Math.abs(exp);
    return sign + digits[0] + (digits.length > 1 ? "." + digits.slice(1) : "") + "e" +
      (exp < 0 ? "-" : "+") + (e < 10 ? "0" + e : String(e));
  }

  function canonical(v) {
    if (v === null) return "null";
    if (v === true) return "true";
    if (v === false) return "false";
    if (v instanceof Num) return v.isInt ? (v.lexeme === "-0" ? "0" : v.lexeme) : pyFloat(v.value);
    if (typeof v === "string") return pyString(v);
    if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
    var keys = Object.keys(v).sort(cmpCodePoints);
    return "{" + keys.map(function (k) { return pyString(k) + ":" + canonical(v[k]); }).join(",") + "}";
  }

  function canonicalBody(doc) {
    var body = Object.create(null);
    Object.keys(doc).forEach(function (k) { if (k !== "signature") body[k] = doc[k]; });
    return new TextEncoder().encode(canonical(body));
  }

  // ---- the receipt schema (contracts/receipt.v1.schema.json), as Python's jsonschema reads it ----

  var HEX = /^[0-9a-f]{64}\n?$/;          // Python's "$" also matches before one final newline
  var REPO = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\n?$/;
  var DIGESTS = ["baseSha256", "headSha256", "buildSha256", "policySha256", "routeSetSha256"];
  var REQUIRED = ["format", "issuerKeyId", "repository", "baseSha256", "headSha256", "buildSha256",
    "policySha256", "routeSetSha256", "versions", "evidence", "coverage", "decision", "findings",
    "cost", "issuedAt", "expiresAt", "algorithm", "publicKey", "signature"];

  function isObj(v) { return v !== null && typeof v === "object" && !Array.isArray(v) && !(v instanceof Num); }
  function isStr(v, min) { return typeof v === "string" && v.length >= (min || 0); }
  function exact(v, required, optional, where) {
    if (!isObj(v)) throw new Invalid(where + ": not an object");
    required.forEach(function (k) { if (!(k in v)) throw new Invalid(where + ": " + k + " is missing"); });
    Object.keys(v).forEach(function (k) {
      if (required.indexOf(k) === -1 && optional.indexOf(k) === -1) throw new Invalid(where + ": " + k + " is not allowed");
    });
  }
  function strings(v, where, minItems) {
    if (!Array.isArray(v)) throw new Invalid(where + ": not a list");
    if (v.length < (minItems || 0)) throw new Invalid(where + ": needs at least " + minItems);
    var seen = Object.create(null);
    v.forEach(function (s) {
      if (!isStr(s, 1)) throw new Invalid(where + ": every item must be a non-empty string");
      if (seen[s]) throw new Invalid(where + ": items must be unique");
      seen[s] = true;
    });
  }

  function validate(doc) {
    exact(doc, REQUIRED, [], "(root)");
    if (doc.format !== FORMAT) throw new Invalid("format: expected " + FORMAT);
    if (!isStr(doc.issuerKeyId, 1)) throw new Invalid("issuerKeyId: not a non-empty string");
    if (!isStr(doc.repository) || !REPO.test(doc.repository)) throw new Invalid("repository: not OWNER/NAME");
    DIGESTS.forEach(function (k) {
      if (!isStr(doc[k]) || !HEX.test(doc[k])) throw new Invalid(k + ": not a sha256 hex digest");
    });
    exact(doc.versions, ["verifier", "adapter", "observer"], [], "versions");
    ["verifier", "adapter", "observer"].forEach(function (k) {
      if (!isStr(doc.versions[k], 1)) throw new Invalid("versions/" + k + ": not a non-empty string");
    });
    exact(doc.evidence, ["grade", "capabilities", "artifacts"], [], "evidence");
    if (["full", "partial", "none"].indexOf(doc.evidence.grade) === -1) throw new Invalid("evidence/grade: not full, partial or none");
    strings(doc.evidence.capabilities, "evidence/capabilities");
    if (!isObj(doc.evidence.artifacts)) throw new Invalid("evidence/artifacts: not an object");
    Object.keys(doc.evidence.artifacts).forEach(function (k) {
      var d = doc.evidence.artifacts[k];
      if (!isStr(d) || !HEX.test(d)) throw new Invalid("evidence/artifacts/" + k + ": not a sha256 hex digest");
    });
    exact(doc.coverage, ["required", "exercised", "results"], [], "coverage");
    strings(doc.coverage.required, "coverage/required", 1);
    strings(doc.coverage.exercised, "coverage/exercised");
    if (!isObj(doc.coverage.results)) throw new Invalid("coverage/results: not an object");
    Object.keys(doc.coverage.results).forEach(function (k) {
      if (["pass", "fail", "not-exercised", "error"].indexOf(doc.coverage.results[k]) === -1) {
        throw new Invalid("coverage/results/" + k + ": not pass, fail, not-exercised or error");
      }
    });
    if (["accept", "reject", "needs-review"].indexOf(doc.decision) === -1) throw new Invalid("decision: not accept, reject or needs-review");
    if (!Array.isArray(doc.findings)) throw new Invalid("findings: not a list");
    doc.findings.forEach(function (f, n) {
      exact(f, ["id"], ["summary"], "findings/" + n);
      if (!isStr(f.id, 1)) throw new Invalid("findings/" + n + "/id: not a non-empty string");
      if ("summary" in f && !isStr(f.summary)) throw new Invalid("findings/" + n + "/summary: not a string");
    });
    exact(doc.cost, ["usd"], [], "cost");
    if (!(doc.cost.usd instanceof Num) || !(doc.cost.usd.value >= 0)) throw new Invalid("cost/usd: not a number of at least 0");
    if (!isStr(doc.issuedAt) || !isStr(doc.expiresAt)) throw new Invalid("issuedAt and expiresAt must be strings");
    if (doc.algorithm !== "ed25519") throw new Invalid("algorithm: expected ed25519");
    if (!isStr(doc.publicKey, 1)) throw new Invalid("publicKey: not a non-empty string");
    if (!isStr(doc.signature, 1)) throw new Invalid("signature: not a non-empty string");
  }

  function readReceipt(text) {
    var doc = parse(text);
    validate(doc);
    canonical(doc);  // refuses anything canonical_v1 would refuse
    return doc;
  }

  function readTrustStore(text) {
    var doc;
    try { doc = parse(text); } catch (e) { throw new Invalid("trust store: " + e.message); }
    if (!isObj(doc) || doc.format !== TRUST_STORE_FORMAT) throw new Invalid("trust store must be " + TRUST_STORE_FORMAT);
    if (!Array.isArray(doc.keys) || !doc.keys.length) throw new Invalid("trust store must contain a non-empty keys list");
    var out = Object.create(null);
    doc.keys.forEach(function (entry) {
      if (!isObj(entry)) throw new Invalid("trust-store key entry must be an object");
      if (!isStr(entry.id, 1) || !isStr(entry.publicKey, 1)) throw new Invalid("trust-store key entry needs id and publicKey");
      if (entry.id in out) throw new Invalid("duplicate key id in trust store: " + entry.id);
      out[entry.id] = entry.publicKey;
    });
    return out;
  }

  // ---- time: RFC 3339 only; anything else Python might read differently, so cannot tell ----

  function daysFromCivil(y, m, d) {
    y -= m <= 2 ? 1 : 0;
    var era = Math.floor(y / 400), yoe = y - era * 400;
    var doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
    var doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
    return era * 146097 + doe - 719468;
  }
  // Microseconds since the epoch, null for a value Python also refuses, CannotTell for other forms.
  function micros(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})?$/.exec(s);
    if (!m) throw new CannotTell("a timestamp is not in the RFC 3339 form this page reads: " + JSON.stringify(s));
    var y = +m[1], mo = +m[2], d = +m[3], h = +m[4], mi = +m[5], se = +m[6];
    var leap = (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
    var dim = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1];
    if (y < 1 || mo < 1 || mo > 12 || d < 1 || d > dim || h > 23 || mi > 59 || se > 59) return null;
    // Python reads a time with no offset as naive, and comparing it with now fails: unparseable there too.
    if (m[8] === undefined) return null;
    var off = 0;
    if (m[8] !== "Z") {
      var oh = +m[8].slice(1, 3), om = +m[8].slice(4, 6);
      if (oh > 23 || om > 59) return null;
      off = (oh * 60 + om) * 60 * (m[8][0] === "-" ? -1 : 1);
    }
    var frac = m[7] ? +(m[7] + "000000").slice(0, 6) : 0;
    return (daysFromCivil(y, mo, d) * 86400 + h * 3600 + mi * 60 + se - off) * 1000000 + frac;
  }

  // ---- Python's repr() of a str or None, for the reason lines ----

  function pyRepr(v) {
    if (v === undefined || v === null) return "None";
    if (typeof v !== "string") return String(v);
    var q = v.indexOf("'") !== -1 && v.indexOf('"') === -1 ? '"' : "'";
    var out = "";
    for (var ch of v) {
      var c = ch.codePointAt(0);
      if (ch === "\\") out += "\\\\";
      else if (ch === q) out += "\\" + q;
      else if (ch === "\n") out += "\\n";
      else if (ch === "\r") out += "\\r";
      else if (ch === "\t") out += "\\t";
      else if (c < 0x20 || (c >= 0x7f && c <= 0xa0) || c === 0xad) out += "\\x" + ("0" + c.toString(16)).slice(-2);
      else out += ch;
    }
    return q + out + q;
  }
  function pyList(items) { return "[" + items.map(pyRepr).join(", ") + "]"; }

  // ---- Ed25519 ----

  var B64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;
  function b64bytes(s, what) {
    // Python's b64decode skips characters outside the alphabet. Only canonical base64 is read here.
    if (!B64.test(s)) throw new CannotTell(what + " is not plain base64, which this page does not read");
    var bin = atob(s), out = new Uint8Array(bin.length);
    for (var k = 0; k < bin.length; k++) out[k] = bin.charCodeAt(k);
    return out;
  }
  function subtle() {
    var c = (typeof crypto !== "undefined" && crypto) || (root && root.crypto);
    return c && c.subtle;
  }
  async function verifySignature(doc, publicKeyB64) {
    var pub = b64bytes(publicKeyB64, "the trusted public key");
    var sig = b64bytes(doc.signature, "the signature");
    var s = subtle();
    if (!s) throw new CannotTell("this browser has no Web Crypto, so it cannot check a signature");
    var key;
    try {
      key = await s.importKey("raw", pub, {name: "Ed25519"}, false, ["verify"]);
    } catch (e) {
      if (e && e.name === "NotSupportedError") throw new CannotTell("this browser cannot check Ed25519 signatures");
      return false;  // not a 32-byte Ed25519 key: Python's verify fails the same way
    }
    try { return await s.verify({name: "Ed25519"}, key, sig, canonicalBody(doc)); } catch (e) { return false; }
  }

  // ---- check_receipt(), line for line ----

  async function checkReceipt(doc, trustStore, opts) {
    opts = opts || {};
    var expectRepo = opts.expectRepo == null ? null : opts.expectRepo;
    var expectHead = opts.expectHead == null ? null : opts.expectHead;
    var expectPolicy = opts.expectPolicy == null ? null : opts.expectPolicy;
    var now = opts.nowMicros != null ? opts.nowMicros : Date.now() * 1000;
    var report = {
      format: FORMAT, valid_signature: false, known_issuer: false, identity_ok: false, policy_ok: false,
      fresh: false, complete: false, clearance: false, decision: doc.decision,
      establishes: [], does_not_establish: [], reasons: []
    };
    function gap(reason, item) {
      if (report.reasons.indexOf(reason) === -1) report.reasons.push(reason);
      item = item === undefined ? reason : item;
      if (report.does_not_establish.indexOf(item) === -1) report.does_not_establish.push(item);
    }
    function dne(item) { return report.does_not_establish.indexOf(item) !== -1; }

    var kid = doc.issuerKeyId;
    var trusted = Object.prototype.hasOwnProperty.call(trustStore, kid) ? trustStore[kid] : null;
    if (trusted === null) {
      report.reasons.push("unknown issuer (key id not in trust store)");
      report.does_not_establish.push("issuer identity");
    } else if (trusted !== doc.publicKey) {
      report.reasons.push("embedded public key does not match trust store");
      report.does_not_establish.push("issuer identity");
    } else {
      report.known_issuer = true;
      if (await verifySignature(doc, trusted)) {
        report.valid_signature = true;
        report.establishes.push("signed by known issuer " + kid);
      } else {
        report.reasons.push("signature does not verify with trusted key");
        report.does_not_establish.push("signature");
      }
    }

    var repoShown = expectRepo !== null && doc.repository === expectRepo;
    var headShown = expectHead !== null && doc.headSha256 === expectHead;
    var policyShown = expectPolicy !== null && doc.policySha256 === expectPolicy;
    if (expectRepo === null) gap("repository not checked");
    else if (doc.repository !== expectRepo) {
      gap("repository mismatch: got " + pyRepr(doc.repository) + ", expected " + pyRepr(expectRepo), "build identity");
    }
    if (expectHead === null) gap("head not checked");
    else if (doc.headSha256 !== expectHead) gap("head digest mismatch", "build identity");
    report.identity_ok = !!(report.valid_signature && repoShown && headShown);
    if (report.identity_ok) {
      report.establishes.push("repository " + doc.repository + " head " + Array.from(doc.headSha256).slice(0, 12).join("") + "…");
    } else if (!dne("build identity") && (dne("repository not checked") || dne("head not checked"))) {
      report.does_not_establish.push("build identity");
    }

    if (expectPolicy === null) gap("policy not checked");
    else if (doc.policySha256 !== expectPolicy) gap("policy digest mismatch", "policy binding");
    report.policy_ok = policyShown;
    if (policyShown && report.valid_signature) report.establishes.push("policy digest matches expectation");
    else if (!policyShown && !dne("policy binding")) report.does_not_establish.push("policy binding");

    var expires = micros(doc.expiresAt), issued = micros(doc.issuedAt);
    var inWindow, bounded, span;
    if (expires === null || issued === null) {
      inWindow = false; bounded = false; span = null;
      gap("unparseable timestamps", "freshness");
    } else {
      span = expires - issued;
      inWindow = issued <= now && now < expires;
      bounded = span > 0 && span <= MAX_VALIDITY;
    }
    if (!inWindow) gap("stale or not-yet-valid receipt", "freshness");
    if (!bounded) {
      if (span !== null && span > MAX_VALIDITY) gap("validity longer than 7 days", "validity within 7 days");
      else gap("validity is not a positive span of at most 7 days", "validity within 7 days");
    }
    report.fresh = !!(inWindow && bounded);
    if (report.fresh) report.establishes.push("within issuedAt..expiresAt, at most 7 days");
    else gap("freshness");

    var cov = doc.coverage;
    var required = cov.required.slice().sort(cmpCodePoints);
    var exercised = cov.exercised;
    var results = cov.results;
    var grade = doc.evidence.grade;
    if (!required.length) gap("no required checks", "at least one required check");
    var missing = required.filter(function (n) { return exercised.indexOf(n) === -1; });
    if (missing.length) gap("removed or missing required checks: " + pyList(missing), "exercised covers required");
    var failed = [];
    required.forEach(function (name) {
      var value = Object.prototype.hasOwnProperty.call(results, name) ? results[name] : null;
      if (value !== "pass") {
        failed.push(name);
        gap("required check " + pyRepr(name) + " is " + pyRepr(value) + ", not pass", "every required check passed");
      }
    });
    if (grade !== "full") gap("evidence grade is " + pyRepr(grade) + ", not full", "full evidence");
    report.complete = required.length > 0 && !missing.length && !failed.length && grade === "full";
    if (report.complete) report.establishes.push("all required checks passed, exercised, on full evidence");
    else gap("completeness of evidence");

    if (doc.decision !== "accept") gap("decision is " + pyRepr(doc.decision) + ", not accept", "decision accept");

    report.clearance = !!(report.valid_signature && report.known_issuer && repoShown && headShown &&
      policyShown && report.fresh && report.complete && doc.decision === "accept");
    if (report.clearance) report.establishes.push("clearance: accept on full evidence");
    else {
      gap("clearance");
      if (report.valid_signature) gap("no clearance", "clearance");
    }
    return report;
  }

  // One call for the page and the tests: texts in, an outcome out. Never throws.
  //   outcome "clearance" | "no-clearance" | "invalid" (trust-check would exit 2) |
  //           "cannot-tell" (this page cannot be sure; use trust-check)
  async function check(receiptText, trustStoreText, opts) {
    try {
      var doc = readReceipt(receiptText);
      var store = readTrustStore(trustStoreText);
      var report = await checkReceipt(doc, store, opts);
      return {outcome: report.clearance ? "clearance" : "no-clearance", report: report};
    } catch (e) {
      if (e instanceof Invalid || e instanceof CannotTell) return {outcome: e.kind, message: e.message};
      return {outcome: "cannot-tell", message: "this page hit an error it did not expect: " + (e && e.message)};
    }
  }

  var api = {check: check, parse: parse, canonical: canonical, pyFloat: pyFloat, micros: micros};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ExpectrailReceipt = api;
})(typeof window !== "undefined" ? window : globalThis);
