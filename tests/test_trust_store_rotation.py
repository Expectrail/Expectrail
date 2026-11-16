"""Trust store v2 (#255): each issuer key has the span it may sign in, and can be retired or revoked.

- A retired key (``notAfter``) is trusted for receipts it issued before it retired, and refused for
  receipts it says it issued at or after.
- A revoked key is refused for every receipt, whatever ``issuedAt`` says: a stolen key can backdate.
- A reader that meets a field it does not know refuses the store, in v1 and v2, so a ``revoked``
  is never read past.
- ``python -m expectrail.receipt trust-store`` edits a store's public material and refuses to write
  anything trust-check would not read.
- The Verify page (docs/verify/receipt-check.js) reports what trust-check reports for every case.

Keys are generated per test and thrown away. No real key is used or written.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from expectrail import receipt as rc
from tests import test_verify_receipt_page as page

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "contracts" / "trust-store.v2.schema.json").read_text(encoding="utf-8"))
EXAMPLE = ROOT / "contracts" / "examples" / "trust-store.v2.json"

T0 = "2026-11-01T00:00:00Z"        # key A starts signing
SWITCH = "2026-11-10T00:00:00Z"    # key B starts, key A retires
NOW = page.NOW                     # 2026-11-15T12:00Z


def pub(key: Ed25519PrivateKey) -> str:
    return page.public_b64(key)


def receipt(key: Ed25519PrivateKey, kid: str, issued: str, *, days: int = 7) -> dict:
    """A clearing receipt signed by ``key`` that says it was issued at ``issued``."""
    doc = page.base_doc(key, kid)
    when = datetime.fromisoformat(issued.replace("Z", "+00:00"))
    doc["issuedAt"] = issued
    doc["expiresAt"] = (when + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return page.sign(doc, key)


def v2(*keys: dict) -> str:
    return json.dumps({"format": rc.TRUST_STORE_V2, "keys": list(keys)})


def check(doc: dict, store: str, now: datetime = NOW) -> dict:
    return rc.check_receipt(doc, rc.parse_trust_store(store), expect_repo=page.REPO, expect_head=page.HEAD,
                            expect_build=page.BUILD, expect_policy=page.POLICY, now=now)


class RotationTest(unittest.TestCase):
    def setUp(self):
        self.a, self.b = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        self.store = v2({"id": "a", "publicKey": pub(self.a), "validFrom": T0, "notAfter": SWITCH},
                        {"id": "b", "publicKey": pub(self.b), "validFrom": SWITCH})

    def test_a_retired_key_clears_what_it_issued_before_it_retired(self):
        report = check(receipt(self.a, "a", "2026-11-09T12:00:00Z"), self.store)
        self.assertTrue(report["clearance"], report["reasons"])
        self.assertTrue(report["known_issuer"])

    def test_a_retired_key_is_refused_for_what_it_says_it_issued_after(self):
        for issued in (SWITCH, "2026-11-12T00:00:00Z"):
            with self.subTest(issued):
                report = check(receipt(self.a, "a", issued), self.store)
                self.assertFalse(report["clearance"])
                self.assertFalse(report["known_issuer"])
                self.assertFalse(report["valid_signature"])
                self.assertIn(f"receipt issued outside the issuer key's validity ({T0} to {SWITCH})", report["reasons"])
                self.assertIn("issuer identity", report["does_not_establish"])

    def test_the_new_key_clears_from_its_start_and_not_before(self):
        self.assertTrue(check(receipt(self.b, "b", "2026-11-12T00:00:00Z"), self.store)["clearance"])
        early = check(receipt(self.b, "b", "2026-11-09T23:59:59Z"), self.store, now=datetime(2026, 11, 10, 1, tzinfo=timezone.utc))
        self.assertFalse(early["clearance"])
        self.assertIn(f"receipt issued outside the issuer key's validity ({SWITCH} to no end)", early["reasons"])

    def test_a_retired_keys_receipts_stop_clearing_when_they_expire(self):
        # Issued a second before it retired, valid 7 days: refused 7 days after notAfter at the latest.
        doc = receipt(self.a, "a", "2026-11-09T23:59:59Z")
        self.assertTrue(check(doc, self.store, now=datetime(2026, 11, 16, 23, tzinfo=timezone.utc))["clearance"])
        late = check(doc, self.store, now=datetime(2026, 11, 17, tzinfo=timezone.utc))
        self.assertFalse(late["clearance"])
        self.assertTrue(late["known_issuer"])
        self.assertIn("stale or not-yet-valid receipt", late["reasons"])

    def test_a_revoked_key_is_refused_whatever_date_the_receipt_carries(self):
        store = v2({"id": "a", "publicKey": pub(self.a), "validFrom": T0,
                    "revoked": {"at": "2026-11-14T00:00:00Z", "reason": "the laptop that held it was lost"}})
        for issued in ("2026-11-09T00:00:00Z", "2026-11-13T23:00:00Z", "2026-11-15T00:00:00Z"):
            with self.subTest(issued):
                report = check(receipt(self.a, "a", issued), store)
                self.assertFalse(report["clearance"])
                self.assertFalse(report["known_issuer"])
                self.assertIn("issuer key revoked at 2026-11-14T00:00:00Z: the laptop that held it was lost",
                              report["reasons"])

    def test_an_issued_at_with_no_offset_or_an_impossible_date_is_outside_the_span(self):
        for issued in ("2026-11-12T00:00:00", "2026-11-31T00:00:00Z", "yesterday"):
            with self.subTest(issued):
                doc = page.base_doc(self.b, "b")
                doc["issuedAt"] = issued
                report = check(page.sign(doc, self.b), self.store)
                self.assertFalse(report["known_issuer"])
                self.assertFalse(report["clearance"])

    def test_a_v1_store_still_trusts_its_keys_for_any_date(self):
        store = page.store_text({"a": pub(self.a)})
        self.assertTrue(check(receipt(self.a, "a", "2026-11-12T00:00:00Z"), store)["clearance"])
        self.assertTrue(check(receipt(self.a, "a", "2026-11-12T00:00:00Z"), json.dumps(
            {"format": rc.TRUST_STORE_FORMAT, "note": "n", "keys": [{"id": "a", "publicKey": pub(self.a), "note": "k"}]}
        ))["clearance"])

    def test_a_revoked_key_cannot_clear_under_another_id(self):
        # The merge guard's probe on #540: K revoked as "old", the same K listed as "alias".
        store = v2({"id": "old", "publicKey": pub(self.a), "validFrom": T0,
                    "revoked": {"at": "2026-11-01T00:00:00Z", "reason": "leaked"}},
                   {"id": "alias", "publicKey": pub(self.a), "validFrom": "2026-01-01T00:00:00Z"})
        with self.assertRaises(rc.ReceiptError) as caught:
            rc.parse_trust_store(store)
        self.assertEqual(str(caught.exception), "trust store lists one publicKey under more than one id: old and alias")

    def test_a_store_built_in_code_with_one_key_under_two_ids_is_still_refused(self):
        # The fallback for a store that never went through parse_trust_store.
        doc = receipt(self.a, "alias", NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
        for revoked_first in (True, False):
            with self.subTest(revoked_first=revoked_first):
                old = rc.TrustKey(pub(self.a), T0, None, "2026-11-01T00:00:00Z", "leaked")
                alias = rc.TrustKey(pub(self.a), "2026-01-01T00:00:00Z")
                store = {"old": old, "alias": alias} if revoked_first else {"alias": alias, "old": old}
                report = rc.check_receipt(doc, store, expect_repo=page.REPO, expect_head=page.HEAD,
                                          expect_build=page.BUILD, expect_policy=page.POLICY, now=NOW)
                self.assertFalse(report["clearance"])
                self.assertFalse(report["known_issuer"])
                self.assertFalse(report["valid_signature"])
                self.assertIn("issuer key revoked at 2026-11-01T00:00:00Z: leaked", report["reasons"])

    def test_a_store_built_in_code_with_plain_keys_still_works(self):
        doc = receipt(self.a, "a", "2026-11-12T00:00:00Z")
        report = rc.check_receipt(doc, {"a": pub(self.a)}, expect_repo=page.REPO, expect_head=page.HEAD,
                                  expect_build=page.BUILD, expect_policy=page.POLICY, now=NOW)
        self.assertTrue(report["clearance"])


def bad_stores(public_key: str) -> dict[str, str]:
    """Stores that must be refused whole: trust-check exits 2, the page says invalid."""
    good = {"id": "a", "publicKey": public_key, "validFrom": T0}

    def with_(**changes):
        entry = dict(good)
        for k, v in changes.items():
            if v is None:
                entry.pop(k)
            else:
                entry[k] = v
        return v2(entry)

    return {
        "v1 key with revoked": json.dumps({"format": rc.TRUST_STORE_FORMAT, "keys": [
            {"id": "a", "publicKey": public_key, "revoked": {"at": T0, "reason": "lost"}}]}),
        "v1 key with notAfter": json.dumps({"format": rc.TRUST_STORE_FORMAT, "keys": [
            {"id": "a", "publicKey": public_key, "notAfter": T0}]}),
        "v1 key with a note that is not text": json.dumps({"format": rc.TRUST_STORE_FORMAT, "keys": [
            {"id": "a", "publicKey": public_key, "note": 3}]}),
        "unknown format": json.dumps({"format": "expectrail.trust-store/v3", "keys": [good]}),
        "v2 unknown top-level field": json.dumps({"format": rc.TRUST_STORE_V2, "keys": [good], "issuer": "x"}),
        "v2 unknown key field": with_(trustedFor="everything"),
        "v2 no validFrom": with_(validFrom=None),
        "v2 validFrom with no offset": with_(validFrom="2026-11-01T00:00:00"),
        "v2 validFrom impossible": with_(validFrom="2026-02-30T00:00:00Z"),
        "v2 validFrom not a string": with_(validFrom=20261101),
        "v2 validFrom with a space": with_(validFrom="2026-11-01 00:00:00Z"),
        "v2 notAfter equal to validFrom": with_(notAfter=T0),
        "v2 notAfter before validFrom": with_(notAfter="2026-10-01T00:00:00Z"),
        "v2 notAfter not a date": with_(notAfter="never"),
        "v2 revoked without reason": with_(revoked={"at": T0}),
        "v2 revoked with empty reason": with_(revoked={"at": T0, "reason": ""}),
        "v2 revoked with an extra field": with_(revoked={"at": T0, "reason": "lost", "by": "x"}),
        "v2 revoked as true": with_(revoked=True),
        "v2 revoked at not a date": with_(revoked={"at": "today", "reason": "lost"}),
        "v2 duplicate id": v2(good, dict(good)),
        # One key under two ids: revoking one id would leave the key trusted under the other (#540 review).
        "v1 one key under two ids": json.dumps({"format": rc.TRUST_STORE_FORMAT, "keys": [
            {"id": "a", "publicKey": public_key}, {"id": "alias", "publicKey": public_key}]}),
        "v2 one key under two ids, one revoked": v2(
            dict(good, revoked={"at": "2026-11-01T00:00:00Z", "reason": "leaked"}),
            {"id": "alias", "publicKey": public_key, "validFrom": "2026-01-01T00:00:00Z"}),
        "v2 one key under two ids, neither revoked": v2(
            good, {"id": "alias", "publicKey": public_key, "validFrom": "2026-01-01T00:00:00Z"}),
        "v2 empty keys": v2(),
    }


class StoreFormatTest(unittest.TestCase):
    def test_the_example_is_read_by_both_the_schema_and_the_reader(self):
        doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(SCHEMA).validate(doc)
        keys = rc.load_trust_store(EXAMPLE)
        self.assertEqual(len(keys), 3)
        self.assertIn("throwaway", doc["note"])
        states = {kid: rc.key_state(k, NOW) for kid, k in keys.items()}
        self.assertTrue(states["example-2026-10"].startswith("retired at 2026-11-01T00:00:00Z"))
        self.assertEqual(states["example-2026-11"], "active since 2026-11-01T00:00:00Z")
        self.assertTrue(states["example-lost-laptop"].startswith("revoked at"))

    def test_every_store_it_cannot_fully_read_is_refused_whole(self):
        for name, text in bad_stores(pub(Ed25519PrivateKey.generate())).items():
            with self.subTest(name), self.assertRaises(rc.ReceiptError):
                rc.parse_trust_store(text)

    def test_the_schema_refuses_the_v2_shapes_the_reader_refuses(self):
        # Date comparisons and real-date checks are the reader's; the schema holds the shape.
        shape_only = {"v2 unknown top-level field", "v2 unknown key field", "v2 no validFrom",
                      "v2 validFrom not a string", "v2 revoked without reason", "v2 revoked with empty reason",
                      "v2 revoked with an extra field", "v2 revoked as true", "v2 empty keys"}
        validator = jsonschema.Draft202012Validator(SCHEMA)
        for name, text in bad_stores(pub(Ed25519PrivateKey.generate())).items():
            if name in shape_only:
                with self.subTest(name):
                    self.assertFalse(validator.is_valid(json.loads(text)))


class TrustCheckCommandTest(unittest.TestCase):
    def run_check(self, doc: dict, store: str) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            r, s = Path(tmp) / "r.json", Path(tmp) / "s.json"
            r.write_text(json.dumps(doc), encoding="utf-8")
            s.write_text(store, encoding="utf-8")
            done = subprocess.run([sys.executable, "-m", "expectrail.receipt", "trust-check", str(r), "--trust-store",
                                   str(s), "--repo", page.REPO, "--expect-head", page.HEAD, "--expect-build",
                                   page.BUILD, "--expect-policy", page.POLICY], capture_output=True, text=True,
                                  cwd=ROOT, timeout=60)
            return done.returncode, done.stdout + done.stderr

    def test_trust_check_refuses_a_revoked_key_and_names_why(self):
        key = Ed25519PrivateKey.generate()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        issued = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        start = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        doc = receipt(key, "k", issued)
        active = v2({"id": "k", "publicKey": pub(key), "validFrom": start})
        code, out = self.run_check(doc, active)
        self.assertEqual(code, 0, out)
        revoked = v2({"id": "k", "publicKey": pub(key), "validFrom": start, "revoked": {"at": issued, "reason": "lost"}})
        code, out = self.run_check(doc, revoked)
        self.assertEqual(code, 1, out)
        self.assertIn("issuer: REVOKED (in the trust store, revoked)", out)
        self.assertIn("identity: not shown (no valid signature from a trusted key)", out)
        self.assertIn(f"issuer key revoked at {issued}: lost", out)
        code, out = self.run_check(doc, bad_stores(pub(key))["v1 key with revoked"])
        self.assertEqual(code, 2, out)
        self.assertIn("Nothing was checked", out)


class EditCommandTest(unittest.TestCase):
    def run_tool(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = rc.main(["trust-store", *args])
        return code, out.getvalue(), err.getvalue()

    def test_a_rotation_made_with_the_commands_checks_as_intended(self):
        a, b = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "trust" / "store.json"
            self.assertEqual(self.run_tool("add", str(store), "--id", "a", "--public-key", pub(a),
                                           "--valid-from", T0)[0], 0)
            self.assertEqual(self.run_tool("add", str(store), "--id", "b", "--public-key", pub(b),
                                           "--valid-from", SWITCH)[0], 0)
            code, out, _ = self.run_tool("retire", str(store), "--id", "a", "--at", SWITCH)
            self.assertEqual(code, 0)
            text = store.read_text(encoding="utf-8")
            self.assertIn(f"sha256 {hashlib.sha256(text.encode()).hexdigest()}", out)
            doc = json.loads(text)
            jsonschema.Draft202012Validator(SCHEMA).validate(doc)
            self.assertEqual(doc["keys"], [
                {"id": "a", "publicKey": pub(a), "validFrom": T0, "notAfter": SWITCH},
                {"id": "b", "publicKey": pub(b), "validFrom": SWITCH}])
            self.assertTrue(check(receipt(a, "a", "2026-11-09T00:00:00Z"), text)["clearance"])
            self.assertFalse(check(receipt(a, "a", "2026-11-11T00:00:00Z"), text)["clearance"])
            self.assertTrue(check(receipt(b, "b", "2026-11-11T00:00:00Z"), text)["clearance"])

            self.assertEqual(self.run_tool("revoke", str(store), "--id", "b", "--reason", "lost",
                                           "--at", "2026-11-15T00:00:00Z")[0], 0)
            text = store.read_text(encoding="utf-8")
            self.assertFalse(check(receipt(b, "b", "2026-11-11T00:00:00Z"), text)["clearance"])
            code, out, _ = self.run_tool("show", str(store))
            self.assertEqual(code, 0)
            self.assertIn(hashlib.sha256(text.encode()).hexdigest(), out)
            self.assertIn("b: revoked at 2026-11-15T00:00:00Z (lost)", out)
            self.assertIn(f"a: retired at {SWITCH}", out)

    def test_each_refusal_leaves_the_store_as_it_was(self):
        a = Ed25519PrivateKey.generate()
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store.json"
            self.assertEqual(self.run_tool("add", str(store), "--id", "a", "--public-key", pub(a),
                                           "--valid-from", T0)[0], 0)
            self.assertEqual(self.run_tool("retire", str(store), "--id", "a", "--at", SWITCH)[0], 0)
            before = store.read_bytes()
            refusals = {
                "same id again": ("add", str(store), "--id", "a", "--public-key", pub(Ed25519PrivateKey.generate())),
                "same key under a new id": ("add", str(store), "--id", "a2", "--public-key", pub(a)),
                "a key in another spelling": ("add", str(store), "--id", "c", "--public-key", pub(a).rstrip("=")),
                "a date with no offset": ("add", str(store), "--id", "c", "--public-key",
                                          pub(Ed25519PrivateKey.generate()), "--valid-from", "2026-11-20T00:00:00"),
                "retired twice": ("retire", str(store), "--id", "a", "--at", "2026-11-11T00:00:00Z"),
                "retire an unknown key": ("retire", str(store), "--id", "zz"),
                "a blank reason": ("revoke", str(store), "--id", "a", "--reason", "  "),
                "an unknown key": ("revoke", str(store), "--id", "zz", "--reason", "lost"),
            }
            for name, args in refusals.items():
                with self.subTest(name):
                    code, _, err = self.run_tool(*args)
                    self.assertEqual(code, 2)
                    self.assertIn("The trust store was not changed", err)
                    self.assertEqual(store.read_bytes(), before)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["store.json"])

    def test_it_refuses_to_retire_a_key_into_an_empty_span(self):
        a = Ed25519PrivateKey.generate()
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store.json"
            self.run_tool("add", str(store), "--id", "a", "--public-key", pub(a), "--valid-from", SWITCH)
            before = store.read_bytes()
            code, _, err = self.run_tool("retire", str(store), "--id", "a", "--at", T0)
            self.assertEqual(code, 2, err)
            self.assertIn("notAfter must be after validFrom", err)
            self.assertEqual(store.read_bytes(), before)

    def test_it_does_not_edit_a_v1_store(self):
        a = Ed25519PrivateKey.generate()
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store.json"
            store.write_text(page.store_text({"a": pub(a)}), encoding="utf-8")
            before = store.read_bytes()
            for args in (("retire", str(store), "--id", "a"), ("revoke", str(store), "--id", "a", "--reason", "lost"),
                         ("add", str(store), "--id", "b", "--public-key", pub(Ed25519PrivateKey.generate()))):
                with self.subTest(args[0]):
                    code, _, err = self.run_tool(*args)
                    self.assertEqual(code, 2)
                    self.assertIn("need expectrail.trust-store/v2", err)
                    self.assertEqual(store.read_bytes(), before)

    def test_a_missing_store_is_created_only_by_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "new.json"
            code, _, err = self.run_tool("retire", str(store), "--id", "a")
            self.assertEqual(code, 2)
            self.assertFalse(store.exists())


class PageParityTest(unittest.TestCase):
    """The Verify page against trust-check on v2 stores, with the page tests' harness."""

    run_js = page.ReceiptPageTest.run_js
    same = page.ReceiptPageTest.same

    @classmethod
    def setUpClass(cls):
        page.req.executable("node")

    def test_the_page_and_trust_check_agree_on_rotation(self):
        a, b = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        full = {"expectRepo": page.REPO, "expectHead": page.HEAD, "expectBuild": page.BUILD,
                "expectPolicy": page.POLICY}
        store = v2({"id": "a", "publicKey": pub(a), "validFrom": T0, "notAfter": SWITCH},
                   {"id": "b", "publicKey": pub(b), "validFrom": SWITCH})
        revoked = v2({"id": "a", "publicKey": pub(a), "validFrom": T0,
                      "revoked": {"at": "2026-11-14T00:00:00Z", "reason": "lost — \"quoted\""}})
        frac = v2({"id": "b", "publicKey": pub(b), "validFrom": "2026-11-10T00:00:00.5+01:00"})

        def raw(key, kid, issued):
            doc = page.base_doc(key, kid)
            doc["issuedAt"] = issued
            return json.dumps(page.sign(doc, key))

        cases = [
            ("retired key, issued before", json.dumps(receipt(a, "a", "2026-11-09T12:00:00Z")), store, full),
            ("retired key, issued at notAfter", json.dumps(receipt(a, "a", SWITCH)), store, full),
            ("retired key, issued after", json.dumps(receipt(a, "a", "2026-11-12T00:00:00Z")), store, full),
            ("new key, issued after start", json.dumps(receipt(b, "b", "2026-11-12T00:00:00Z")), store, full),
            ("new key, issued before start", json.dumps(receipt(b, "b", "2026-11-09T23:59:59Z")), store, full),
            ("revoked, issued before revocation", json.dumps(receipt(a, "a", "2026-11-09T00:00:00Z")), revoked, full),
            ("revoked, issued after", json.dumps(receipt(a, "a", "2026-11-15T00:00:00Z")), revoked, full),
            ("offset and fraction, just inside", raw(b, "b", "2026-11-09T23:00:00.500001Z"), frac, full),
            ("offset and fraction, just outside", raw(b, "b", "2026-11-09T23:00:00.4Z"), frac, full),
            ("issued with no offset", raw(b, "b", "2026-11-12T00:00:00"), store, full),
            ("issued on an impossible date", raw(b, "b", "2026-11-31T00:00:00Z"), store, full),
            ("v2 key not in store", json.dumps(receipt(a, "c", "2026-11-12T00:00:00Z")), store, full),
            ("nothing expected", json.dumps(receipt(a, "a", "2026-11-09T12:00:00Z")), store, {}),
        ]
        cases += [(name, json.dumps(receipt(a, "a", "2026-11-09T12:00:00Z")), text, full)
                  for name, text in bad_stores(pub(a)).items()]
        self.same(cases)
        js = self.run_js([{"receipt": r, "store": s, "opts": dict(o, nowMicros=page.NOW_MICROS)} for _, r, s, o in cases])
        outcome = {name: got["outcome"] for (name, *_), got in zip(cases, js)}
        self.assertEqual(outcome["retired key, issued before"], "clearance")
        self.assertEqual(outcome["new key, issued after start"], "clearance")
        self.assertEqual(outcome["offset and fraction, just inside"], "no-clearance")  # expired by NOW; issuer known
        for name in bad_stores(pub(a)):
            self.assertEqual(outcome[name], "invalid", name)
        names = [c[0] for c in cases]
        for name in ("v1 one key under two ids", "v2 one key under two ids, one revoked"):
            self.assertEqual(js[names.index(name)]["message"],
                             "trust store lists one publicKey under more than one id: a and alias", name)
        for name in ("retired key, issued at notAfter", "retired key, issued after", "new key, issued before start",
                     "revoked, issued before revocation", "revoked, issued after", "offset and fraction, just outside",
                     "issued with no offset", "issued on an impossible date"):
            self.assertEqual(outcome[name], "no-clearance", name)
            self.assertFalse(js[[c[0] for c in cases].index(name)]["report"]["known_issuer"], name)


if __name__ == "__main__":
    unittest.main()


class PageWordsInBrowserTest(unittest.TestCase):
    """The page's fact lines for a revoked key: in the store and revoked, and identity not shown,
    never "not in your trust store" or "does not match" when the digests asked for did match."""

    @classmethod
    def setUpClass(cls):
        page.req.require_tool("Playwright Chromium")

    def test_a_revoked_key_reads_as_revoked_and_identity_as_not_shown(self):
        import functools
        import http.server
        import threading
        from playwright.sync_api import sync_playwright

        key = Ed25519PrivateKey.generate()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        stamp = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        doc = receipt(key, "k", stamp(now - timedelta(hours=1)))
        store = v2({"id": "k", "publicKey": pub(key), "validFrom": stamp(now - timedelta(days=1)),
                    "revoked": {"at": stamp(now), "reason": "lost"}})

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(ROOT / "docs")))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                tab = browser.new_page(viewport={"width": 390, "height": 900})
                tab.goto(f"http://127.0.0.1:{server.server_port}/verify/")
                tab.fill("#receipt-text", json.dumps(doc))
                tab.fill("#store-text", store)
                for field, value in (("#expect-repo", page.REPO), ("#expect-head", page.HEAD),
                                     ("#expect-build", page.BUILD), ("#expect-policy", page.POLICY)):
                    tab.fill(field, value)
                tab.click("#check")
                tab.wait_for_selector("#result:not([hidden])")
                text = tab.inner_text("#result")
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
        self.assertIn("No clearance", text)
        self.assertIn("in your trust store, and revoked", text)
        self.assertIn("not shown: no valid signature from a trusted key", text)
        self.assertNotIn("not in your trust store", text)
        self.assertNotIn("does not match", text)
        self.assertIn(f"issuer key revoked at {stamp(now)}: lost", text)
