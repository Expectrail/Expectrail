"""The browser receipt check (docs/verify/receipt-check.js) against trust-check (expectrail/receipt.py).

The page must never say more than `python -m expectrail.receipt trust-check` would: for every receipt
here it gives the same report, field for field, or it says "cannot tell" and gives no clearance.
The signature is over Python's canonical JSON, so the page has to rebuild those bytes exactly; the
float and key-order cases below are where a JavaScript JSON.stringify would differ.

Keys are generated per test and thrown away. No real key is used or written.
"""
from __future__ import annotations

import base64
import copy
import json
import random
import struct
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from expectrail import receipt as rc
from expectrail.contracts import ContractError, canonical_v1, strict_loads
from tests import tool_requirements as req

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "docs" / "verify" / "receipt-check.js"
NOW = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
NOW_MICROS = int(NOW.timestamp()) * 1_000_000
REPO = "Expectrail/Expectrail"
HEAD = "b" * 64
POLICY = "d" * 64

HARNESS = r"""
const r = require(process.argv[1]);
let input = "";
process.stdin.on("data", d => input += d);
process.stdin.on("end", async () => {
  const out = [];
  for (const c of JSON.parse(input)) {
    if (c.canonical !== undefined) { out.push(r.canonical(r.parse(c.canonical))); continue; }
    out.push(await r.check(c.receipt, c.store, c.opts));
  }
  process.stdout.write(JSON.stringify(out));
});
"""


def public_b64(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def store_text(entries: dict[str, str]) -> str:
    return json.dumps({"format": rc.TRUST_STORE_FORMAT, "keys": [{"id": k, "publicKey": v} for k, v in entries.items()]})


def base_doc(key: Ed25519PrivateKey, kid: str = "ci-2026") -> dict:
    doc = json.loads((ROOT / "contracts/examples/receipt.v1.json").read_text(encoding="utf-8"))
    doc.pop("signature")
    doc.update(issuerKeyId=kid, publicKey=public_b64(key), headSha256=HEAD, policySha256=POLICY,
               issuedAt="2026-11-15T00:00:00Z", expiresAt="2026-11-22T00:00:00Z")
    return doc


def sign(doc: dict, key: Ed25519PrivateKey) -> dict:
    return rc.write_receipt(copy.deepcopy(doc), key)


def python_check(receipt_text: str, store: str, opts: dict) -> dict:
    """What trust-check decides, in the shape check() returns (exit 2 is "invalid")."""
    try:
        doc = strict_loads(receipt_text)
        rc._validate_receipt(doc)
        trust = strict_loads(store)
        if not isinstance(trust, dict) or trust.get("format") != rc.TRUST_STORE_FORMAT or not trust.get("keys"):
            raise rc.ReceiptError("trust store")
        entries = {}
        for e in trust["keys"]:
            if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not e.get("id") \
                    or not isinstance(e.get("publicKey"), str) or not e.get("publicKey") or e["id"] in entries:
                raise rc.ReceiptError("trust store entry")
            entries[e["id"]] = e["publicKey"]
    except (ContractError, ValueError):
        return {"outcome": "invalid"}
    report = rc.check_receipt(doc, entries, expect_repo=opts.get("expectRepo"), expect_head=opts.get("expectHead"),
                              expect_policy=opts.get("expectPolicy"), now=NOW)
    return {"outcome": "clearance" if report["clearance"] else "no-clearance", "report": report}


class ReceiptPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        req.executable("node")

    def run_js(self, cases: list[dict]) -> list:
        done = subprocess.run(["node", "-e", HARNESS, str(CHECKER)], input=json.dumps(cases), capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def same(self, cases: list[tuple[str, str, str, dict]], *, cannot_tell: frozenset = frozenset()):
        """Each case: (name, receipt text, trust store text, expectations)."""
        js = self.run_js([{"receipt": r, "store": s, "opts": dict(o, nowMicros=NOW_MICROS)} for _, r, s, o in cases])
        for (name, r, s, o), got in zip(cases, js):
            with self.subTest(name):
                want = python_check(r, s, o)
                if name in cannot_tell:
                    self.assertEqual(got["outcome"], "cannot-tell", got)
                    self.assertNotEqual(want["outcome"], "invalid", "a cannot-tell case should be one Python reads")
                    continue
                self.assertEqual(got["outcome"], want["outcome"], got.get("message"))
                if "report" in want:
                    self.assertEqual(got["report"], want["report"])

    def test_the_page_reports_what_trust_check_reports(self):
        key, other = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        store = store_text({"ci-2026": public_b64(key)})
        full = {"expectRepo": REPO, "expectHead": HEAD, "expectPolicy": POLICY}
        doc = base_doc(key)
        good = sign(doc, key)

        def variant(**changes):
            d = copy.deepcopy(doc)
            for path, value in changes.items():
                target = d
                *parents, last = path.split("__")
                for p in parents:
                    target = target[p]
                target[last] = value
            return json.dumps(sign(d, key), indent=2)

        tampered = dict(good, decision="accept", buildSha256="f" * 64)
        other_signed = dict(sign(doc, other), publicKey=public_b64(key))
        cases = [
            ("clearance", json.dumps(good, indent=2), store, full),
            ("clearance, compact and ascii-escaped", json.dumps(good, ensure_ascii=True), store, full),
            ("nothing asked", json.dumps(good), store, {}),
            ("only the repository asked", json.dumps(good), store, {"expectRepo": REPO}),
            ("repository mismatch", json.dumps(good), store, dict(full, expectRepo="Someone/Else")),
            ("head mismatch", json.dumps(good), store, dict(full, expectHead="a" * 64)),
            ("policy mismatch", json.dumps(good), store, dict(full, expectPolicy="e" * 64)),
            ("a field changed after signing", json.dumps(tampered), store, full),
            ("signed by another key", json.dumps(other_signed), store, full),
            ("unknown issuer", json.dumps(good), store_text({"someone": public_b64(key)}), full),
            ("embedded key is not the trusted one", json.dumps(good), store_text({"ci-2026": public_b64(other)}), full),
            ("trusted key is not a key", json.dumps(dict(good, publicKey="AAAA")), store_text({"ci-2026": "AAAA"}), full),
            ("expired", variant(issuedAt="2026-11-01T00:00:00Z", expiresAt="2026-11-08T00:00:00Z"), store, full),
            ("not yet valid", variant(issuedAt="2026-11-16T00:00:00Z", expiresAt="2026-11-17T00:00:00Z"), store, full),
            ("eight days", variant(issuedAt="2026-11-14T00:00:00Z", expiresAt="2026-11-22T00:00:00Z"), store, full),
            ("seven days and a microsecond", variant(issuedAt="2026-11-15T00:00:00Z",
                                                     expiresAt="2026-11-22T00:00:00.000001Z"), store, full),
            ("zero span", variant(issuedAt="2026-11-15T00:00:00Z", expiresAt="2026-11-15T00:00:00Z"), store, full),
            ("offsets and fractions", variant(issuedAt="2026-11-15T05:30:00.25+05:30",
                                              expiresAt="2026-11-21T19:00:00-05:00"), store, full),
            ("naive timestamps", variant(issuedAt="2026-11-15T00:00:00", expiresAt="2026-11-20T00:00:00"), store, full),
            ("an impossible date", variant(expiresAt="2026-02-30T00:00:00Z"), store, full),
            ("a required check not exercised", variant(coverage__exercised=["regression", "gameplay"]), store, full),
            ("a required check failed", variant(coverage__results={"regression": "pass", "gameplay": "fail",
                                                                   "clean": "pass", "held-out": "error"}), store, full),
            ("a required check has no result", variant(coverage__results={"regression": "pass"}), store, full),
            ("partial evidence", variant(evidence__grade="partial"), store, full),
            ("decision reject", variant(decision="reject"), store, full),
            ("decision needs-review", variant(decision="needs-review"), store, full),
            ("check names with quotes", variant(coverage__required=["it's", 'say "x"', "a\\b"],
                                                coverage__exercised=["it's"]), store, full),
            ("schema: an extra field", json.dumps(dict(good, extra=1)), store, full),
            ("schema: no required checks", json.dumps(dict(good, coverage=dict(good["coverage"], required=[]))), store, full),
            ("schema: bad digest", json.dumps(dict(good, headSha256="B" * 64)), store, full),
            ("schema: negative cost", json.dumps(dict(good, cost={"usd": -1})), store, full),
            ("schema: wrong format", json.dumps(dict(good, format="expectrail.receipt/v2")), store, full),
            ("duplicate key", json.dumps(good)[:-1] + ', "decision": "accept"}', store, full),
            ("NaN", json.dumps(good).replace('"usd": 0.0', '"usd": NaN'), store, full),
            ("a number too large", json.dumps(good).replace('"usd": 0.0', '"usd": 1e400'), store, full),
            ("a lone surrogate", json.dumps(dict(good, findings=[{"id": "x", "summary": "\ud800"}]), ensure_ascii=True),
             store, full),
            ("trust store: wrong format", json.dumps(good), json.dumps({"format": "x", "keys": []}), full),
            ("trust store: duplicate id", json.dumps(good), json.dumps({"format": rc.TRUST_STORE_FORMAT, "keys": [
                {"id": "ci-2026", "publicKey": public_b64(key)}, {"id": "ci-2026", "publicKey": public_b64(key)}]}), full),
            ("not JSON", "{", store, full),
        ]
        self.same(cases)

    def test_canonical_bytes_survive_floats_unicode_and_key_order(self):
        key = Ed25519PrivateKey.generate()
        store = store_text({"ci-2026": public_b64(key)})
        full = {"expectRepo": REPO, "expectHead": HEAD, "expectPolicy": POLICY}
        cases = []
        for usd in (0, 0.1, 1e-05, 2.5, 1e16, 123456789.123, 5e-324, 7):
            d = base_doc(key)
            d["cost"]["usd"] = usd
            cases.append((f"cost {usd!r}", json.dumps(sign(d, key)), store, full))
        d = base_doc(key)
        # Python sorts keys by code point; UTF-16 order would put the emoji before U+FFFD.
        d["evidence"]["artifacts"] = {"�": "1" * 64, "\U0001f600": "2" * 64, "é": "3" * 64, "Z": "4" * 64}
        d["findings"] = [{"id": "f1", "summary": "tab\there, bell\x07, quote \" and slash \\ and é 漢 \U0001f600"}]
        signed = sign(d, key)
        cases.append(("unicode, raw", json.dumps(signed, ensure_ascii=False), store, full))
        cases.append(("unicode, escaped", json.dumps(signed, ensure_ascii=True), store, full))
        # The same value written another way in the file still verifies: the signature is over values.
        cases.append(("cost written as 0.0e0", json.dumps(signed).replace('"usd": 0.0', '"usd": 0.0e0'), store, full))
        self.same(cases)
        got = self.run_js([{"receipt": r, "store": s, "opts": dict(o, nowMicros=NOW_MICROS)} for _, r, s, o in cases])
        self.assertTrue(all(g["outcome"] == "clearance" for g in got), [g.get("report", g) for g in got])

    def test_float_repr_matches_python_on_random_doubles(self):
        rnd = random.Random(265)
        values = [struct.unpack("<d", struct.pack("<Q", rnd.getrandbits(64)))[0] for _ in range(1500)]
        values += [rnd.uniform(-1e6, 1e6) for _ in range(500)]
        values += [10.0 ** e for e in range(-30, 30)] + [-0.0, 0.5, 1 / 3, 9007199254740993.0, 1e22, 1e21]
        values = [v for v in values if v == v and abs(v) != float("inf")]
        texts = [json.dumps({"n": v, "i": int(v) if abs(v) < 1e30 else 1}) for v in values]
        got = self.run_js([{"canonical": t} for t in texts])
        for t, g in zip(texts, got):
            self.assertEqual(g, canonical_v1(json.loads(t)).decode(), t)

    def test_forms_it_cannot_reproduce_say_cannot_tell_and_never_clear(self):
        key = Ed25519PrivateKey.generate()
        store = store_text({"ci-2026": public_b64(key)})
        full = {"expectRepo": REPO, "expectHead": HEAD, "expectPolicy": POLICY}
        d = base_doc(key)
        d["issuedAt"] = "2026-11-15 00:00:00+00:00"  # Python reads a space; the page reads RFC 3339 only
        spaced = json.dumps(sign(d, key))
        good = sign(base_doc(key), key)
        junk = dict(good, signature=good["signature"][:10] + "\n" + good["signature"][10:])  # Python skips the newline
        unpadded = dict(good, signature=good["signature"].rstrip("="))
        self.same([
            ("a space in a timestamp", spaced, store, full),
            ("a newline inside the signature", json.dumps(junk), store, full),
            ("unpadded signature", json.dumps(unpadded), store, full),
        ], cannot_tell=frozenset({"a space in a timestamp", "a newline inside the signature", "unpadded signature"}))

    def test_the_published_samples_are_what_they_say(self):
        folder = ROOT / "docs" / "verify" / "samples"
        store = (folder / "test-trust-store.json").read_text(encoding="utf-8")
        trust = json.loads(store)
        self.assertIn("throwaway", trust["note"])
        for name, decision in (("test-receipt-accept.json", "accept"), ("test-receipt-reject.json", "reject")):
            text = (folder / name).read_text(encoding="utf-8")
            doc = rc.read_receipt(folder / name)
            self.assertEqual(doc["decision"], decision)
            self.assertTrue(doc["issuerKeyId"].startswith("throwaway-test-key"))
            report = rc.check_receipt(doc, rc.load_trust_store(folder / "test-trust-store.json"),
                                      expect_repo=doc["repository"], expect_head=doc["headSha256"],
                                      expect_policy=doc["policySha256"],
                                      now=datetime.fromisoformat(doc["issuedAt"].replace("Z", "+00:00")) + timedelta(hours=1))
            self.assertTrue(report["valid_signature"], name)
            self.assertEqual(report["clearance"], decision == "accept")
            self.assertNotIn("PRIVATE", text.upper())


class ReceiptPageInBrowserTest(unittest.TestCase):
    """The page itself, in Chromium: what it shows for a clearance, a reject and a non-receipt."""

    @classmethod
    def setUpClass(cls):
        req.require_tool("Playwright Chromium")

    def test_the_page_shows_only_what_the_check_decided(self):
        import functools
        import http.server
        import threading
        from playwright.sync_api import sync_playwright

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(ROOT / "docs")))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}/verify/"
        sample = json.loads((ROOT / "docs/verify/samples/test-receipt-accept.json").read_text(encoding="utf-8"))
        inside = datetime.fromisoformat(sample["issuedAt"].replace("Z", "+00:00")) + timedelta(hours=1)
        requests = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.on("request", lambda r: requests.append(r.url))
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.clock.set_fixed_time(inside)
            page.goto(url)
            page.click("#sample-accept")
            page.wait_for_selector("#outcome[data-tone='pass']")
            self.assertIn("Clearance", page.inner_text("#outcome"))
            self.assertIn("throwaway", page.inner_text("#sample-note"))
            page.click("#sample-reject")
            page.wait_for_selector("#outcome[data-tone='fail']")
            self.assertIn("No clearance", page.inner_text("#outcome"))
            self.assertIn("decision is 'reject', not accept", page.inner_text("#details"))
            page.fill("#receipt-text", "{}")
            page.click("#check")
            page.wait_for_selector("#outcome[data-tone='review']")
            self.assertIn("Not a receipt", page.inner_text("#outcome"))
            # Clearing the expected head is "not checked", never a pass.
            page.click("#sample-accept")
            page.wait_for_selector("#outcome[data-tone='pass']")
            page.fill("#expect-head", "")
            page.click("#check")
            page.wait_for_selector("#outcome[data-tone='fail']")
            self.assertIn("head not checked", page.inner_text("#details"))
            browser.close()
        self.assertEqual(errors, [])
        self.assertTrue(all(u.startswith(url.rsplit("/verify/", 1)[0]) for u in requests), requests)


if __name__ == "__main__":
    unittest.main()
