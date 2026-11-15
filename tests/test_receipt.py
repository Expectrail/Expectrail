"""Tests for receipt v1: format, Ed25519 with offline trust store, trust-check.

Keys are generated in the test; no real key is written to a file.
"""
from __future__ import annotations

import base64
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from expectrail.contracts import ContractError
from expectrail.receipt import (
    ReceiptError,
    check_receipt,
    load_trust_store,
    read_receipt,
    sign_receipt,
    write_receipt,
)


def _key() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.generate()
    pub = base64.b64encode(
        private.public_key().public_bytes_raw()
    ).decode("ascii")
    return private, pub


def _base_doc(pub: str, kid: str = "test-issuer") -> dict:
    now = datetime.now(timezone.utc)
    return {
        "format": "expectrail.receipt/v1",
        "issuerKeyId": kid,
        "repository": "Expectrail/Expectrail",
        "baseSha256": "a" * 64,
        "headSha256": "b" * 64,
        "buildSha256": "c" * 64,
        "policySha256": "d" * 64,
        "routeSetSha256": "e" * 64,
        "versions": {"verifier": "0.1.0", "adapter": "godot", "observer": "sam"},
        "evidence": {
            "grade": "full",
            "capabilities": ["frames"],
            "artifacts": {"replay": "1" * 64},
        },
        "coverage": {
            "required": ["regression", "gameplay"],
            "exercised": ["regression", "gameplay"],
            "results": {"regression": "pass", "gameplay": "pass"},
        },
        "decision": "accept",
        "findings": [],
        "cost": {"usd": 0.0},
        "issuedAt": now.isoformat(),
        "expiresAt": (now + timedelta(days=7)).isoformat(),
        "algorithm": "ed25519",
        "publicKey": pub,
    }


def _expect(doc: dict) -> dict:
    """The expectations a clearance has to be shown, taken from the receipt itself."""
    return {
        "expect_repo": doc["repository"],
        "expect_head": doc["headSha256"],
        "expect_policy": doc["policySha256"],
    }


def _report(signed: dict, pub: str, **kw) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "store.json"
        _store(signed["issuerKeyId"], pub, store_path)
        store = load_trust_store(store_path)
        asked = _expect(signed)
        asked.update(kw)
        return check_receipt(signed, store, **asked)


def _store(kid: str, pub: str, path: Path) -> None:
    doc = {
        "format": "expectrail.trust-store/v1",
        "keys": [{"id": kid, "publicKey": pub}],
    }
    path.write_text(json.dumps(doc) + "\n", encoding="utf-8")


class ReceiptFormatTest(unittest.TestCase):
    def test_example_loads(self):
        path = Path("contracts/examples/receipt.v1.json")
        from expectrail.receipt import read_receipt
        doc = read_receipt(path)
        self.assertEqual(doc["format"], "expectrail.receipt/v1")

    def test_write_and_read_roundtrip(self):
        private, pub = _key()
        doc = _base_doc(pub)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            signed = write_receipt(doc, private, path)
            loaded = read_receipt(path)
            self.assertEqual(loaded["signature"], signed["signature"])
            self.assertNotIn("signature", doc)  # original untouched

    def test_duplicate_keys_rejected(self):
        text = '{"format": "expectrail.receipt/v1", "format": "expectrail.receipt/v1"}'
        with self.assertRaises(ContractError):
            from expectrail.contracts import strict_loads
            strict_loads(text)

    def test_non_finite_rejected(self):
        private, pub = _key()
        doc = _base_doc(pub)
        doc["cost"]["usd"] = float("nan")
        with self.assertRaises(ContractError):
            write_receipt(doc, private)


class TrustStoreTest(unittest.TestCase):
    def test_known_issuer_passes(self):
        private, pub = _key()
        doc = _base_doc(pub)
        signed = write_receipt(doc, private)
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            _store("test-issuer", pub, store_path)
            store = load_trust_store(store_path)
            report = check_receipt(signed, store, **_expect(signed))
            self.assertTrue(report["valid_signature"])
            self.assertTrue(report["known_issuer"])
            self.assertTrue(report["identity_ok"])
            self.assertTrue(report["policy_ok"])
            self.assertTrue(report["clearance"])

    def test_unknown_issuer_fails(self):
        private, pub = _key()
        doc = _base_doc(pub)
        signed = write_receipt(doc, private)
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            other_priv, other_pub = _key()
            _store("other", other_pub, store_path)
            store = load_trust_store(store_path)
            report = check_receipt(signed, store)
            self.assertFalse(report["known_issuer"])
            self.assertFalse(report["clearance"])
            self.assertIn("unknown issuer", " ".join(report["reasons"]))

    def test_embedded_key_not_trusted(self):
        """A self-signed receipt whose key is only inside the receipt is refused."""
        private, pub = _key()
        doc = _base_doc(pub, kid="self")
        signed = write_receipt(doc, private)
        # Trust store has a different key.
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            _, other_pub = _key()
            _store("someone-else", other_pub, store_path)
            store = load_trust_store(store_path)
            report = check_receipt(signed, store)
            self.assertFalse(report["known_issuer"])
            self.assertFalse(report["clearance"])

    def test_altered_evidence_fails_signature(self):
        private, pub = _key()
        doc = _base_doc(pub)
        signed = write_receipt(doc, private)
        signed["evidence"]["artifacts"]["replay"] = "f" * 64
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            _store("test-issuer", pub, store_path)
            store = load_trust_store(store_path)
            report = check_receipt(signed, store)
            self.assertFalse(report["valid_signature"])
            self.assertFalse(report["clearance"])

    def test_substituted_head_fails(self):
        private, pub = _key()
        doc = _base_doc(pub)
        signed = write_receipt(doc, private)
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            _store("test-issuer", pub, store_path)
            store = load_trust_store(store_path)
            report = check_receipt(signed, store, expect_head="0" * 64)
            self.assertFalse(report["identity_ok"])
            self.assertFalse(report["clearance"])

    def test_substituted_build_detected_as_identity(self):
        private, pub = _key()
        doc = _base_doc(pub)
        signed = write_receipt(doc, private)
        # Tampering the build digest breaks the signature.
        signed["buildSha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            _store("test-issuer", pub, store_path)
            store = load_trust_store(store_path)
            report = check_receipt(signed, store)
            self.assertFalse(report["valid_signature"])

    def test_stale_receipt_fails(self):
        private, pub = _key()
        doc = _base_doc(pub)
        past = datetime.now(timezone.utc) - timedelta(days=30)
        doc["issuedAt"] = past.isoformat()
        doc["expiresAt"] = (past + timedelta(days=1)).isoformat()
        signed = write_receipt(doc, private)
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            _store("test-issuer", pub, store_path)
            store = load_trust_store(store_path)
            report = check_receipt(signed, store)
            self.assertFalse(report["fresh"])
            self.assertFalse(report["clearance"])

    def test_removed_required_check_no_clearance(self):
        private, pub = _key()
        doc = _base_doc(pub)
        doc["coverage"]["exercised"] = ["regression"]  # gameplay removed
        signed = write_receipt(doc, private)
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            _store("test-issuer", pub, store_path)
            store = load_trust_store(store_path)
            report = check_receipt(signed, store)
            self.assertTrue(report["valid_signature"])
            self.assertFalse(report["complete"])
            self.assertFalse(report["clearance"])
            self.assertIn("no clearance", report["reasons"])

    def test_another_repository_fails(self):
        private, pub = _key()
        doc = _base_doc(pub)
        doc["repository"] = "other/repo"
        signed = write_receipt(doc, private)
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            _store("test-issuer", pub, store_path)
            store = load_trust_store(store_path)
            report = check_receipt(signed, store, expect_repo="Expectrail/Expectrail")
            self.assertFalse(report["identity_ok"])
            self.assertFalse(report["clearance"])

    def test_insufficient_evidence_no_clearance(self):
        private, pub = _key()
        doc = _base_doc(pub)
        doc["evidence"]["grade"] = "partial"
        signed = write_receipt(doc, private)
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "store.json"
            _store("test-issuer", pub, store_path)
            store = load_trust_store(store_path)
            report = check_receipt(signed, store)
            self.assertTrue(report["valid_signature"])
            self.assertFalse(report["clearance"])
            self.assertIn("no clearance", report["reasons"])


class ClearanceAllowListTest(unittest.TestCase):
    """Clearance is granted only for what was positively shown. Each case is false."""

    def test_a_failed_required_check_is_not_clearance(self):
        private, pub = _key()
        doc = _base_doc(pub)
        doc["coverage"]["results"]["gameplay"] = "fail"
        signed = write_receipt(doc, private)
        report = _report(signed, pub)
        self.assertTrue(report["valid_signature"])
        self.assertFalse(report["clearance"])
        self.assertIn("every required check passed", report["does_not_establish"])
        self.assertTrue(any("gameplay" in r and "fail" in r for r in report["reasons"]))

    def test_an_error_required_check_is_not_clearance(self):
        private, pub = _key()
        doc = _base_doc(pub)
        doc["coverage"]["results"]["gameplay"] = "error"
        signed = write_receipt(doc, private)
        report = _report(signed, pub)
        self.assertFalse(report["clearance"])
        self.assertTrue(any("gameplay" in r and "error" in r for r in report["reasons"]))

    def test_a_not_exercised_required_check_is_not_clearance(self):
        private, pub = _key()
        doc = _base_doc(pub)
        doc["coverage"]["results"]["gameplay"] = "not-exercised"
        signed = write_receipt(doc, private)
        report = _report(signed, pub)
        self.assertFalse(report["clearance"])
        self.assertIn("every required check passed", report["does_not_establish"])
        self.assertTrue(any("not-exercised" in r for r in report["reasons"]))

    def test_an_empty_required_list_is_not_clearance(self):
        private, pub = _key()
        doc = _base_doc(pub)
        doc["coverage"] = {"required": [], "exercised": [], "results": {}}
        with self.assertRaises(ContractError):
            write_receipt(dict(doc), private)
        signed = dict(doc)
        signed["signature"] = sign_receipt(signed, private)
        report = _report(signed, pub)
        self.assertTrue(report["valid_signature"])
        self.assertFalse(report["clearance"])
        self.assertIn("at least one required check", report["does_not_establish"])

    def test_repository_not_checked_is_not_clearance(self):
        private, pub = _key()
        doc = _base_doc(pub)
        signed = write_receipt(doc, private)
        report = _report(signed, pub, expect_repo=None)
        self.assertFalse(report["identity_ok"])
        self.assertFalse(report["clearance"])
        self.assertIn("repository not checked", report["does_not_establish"])

    def test_head_not_checked_is_not_clearance(self):
        private, pub = _key()
        doc = _base_doc(pub)
        signed = write_receipt(doc, private)
        report = _report(signed, pub, expect_head=None)
        self.assertFalse(report["identity_ok"])
        self.assertFalse(report["clearance"])
        self.assertIn("head not checked", report["does_not_establish"])

    def test_policy_not_checked_is_not_clearance(self):
        private, pub = _key()
        doc = _base_doc(pub)
        signed = write_receipt(doc, private)
        report = _report(signed, pub, expect_policy=None)
        self.assertFalse(report["policy_ok"])
        self.assertFalse(report["clearance"])
        self.assertIn("policy not checked", report["does_not_establish"])

    def test_validity_longer_than_seven_days_is_not_clearance(self):
        private, pub = _key()
        doc = _base_doc(pub)
        now = datetime.now(timezone.utc)
        doc["issuedAt"] = now.isoformat()
        doc["expiresAt"] = (now + timedelta(days=100 * 365)).isoformat()
        signed = write_receipt(doc, private)
        report = _report(signed, pub, now=now + timedelta(seconds=1))
        self.assertTrue(report["valid_signature"])
        self.assertFalse(report["fresh"])
        self.assertFalse(report["clearance"])
        self.assertIn("validity within 7 days", report["does_not_establish"])
        self.assertTrue(any("7 days" in r for r in report["reasons"]))


class TrustCheckCliTest(unittest.TestCase):
    def test_cli_clearance(self):
        from expectrail.receipt import main
        private, pub = _key()
        doc = _base_doc(pub)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt_path = tmp_path / "r.json"
            store_path = tmp_path / "s.json"
            write_receipt(doc, private, receipt_path)
            _store("test-issuer", pub, store_path)
            code = main([
                "trust-check", str(receipt_path),
                "--trust-store", str(store_path),
                "--repo", "Expectrail/Expectrail",
                "--expect-head", "b" * 64,
                "--expect-policy", "d" * 64,
            ])
            self.assertEqual(code, 0)

    def test_cli_without_expectations_is_not_clearance(self):
        from expectrail.receipt import main
        private, pub = _key()
        doc = _base_doc(pub)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            receipt_path = tmp_path / "r.json"
            store_path = tmp_path / "s.json"
            write_receipt(doc, private, receipt_path)
            _store("test-issuer", pub, store_path)
            code = main(["trust-check", str(receipt_path), "--trust-store", str(store_path)])
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
