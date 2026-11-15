"""Release gate, the receipt rows of identity and authority (#258): wrong build or head, unknown signer,
expired receipt.

Clearance for a receipt is the receipt verifier's: ``python3 -m expectrail.receipt trust-check`` exits 0
and prints "clearance: yes". Every test here runs that command as its own process, against a trust store
file, and asserts it does not.

Where the receipts come from. The trusted job does not write receipts yet (#255), so each receipt here
is made by the test from a real job: ``expectrail verify`` runs the bundled game with Godot, once
unchanged (accept) and once with the seeded bug (reject), and the receipt carries that job's own
digests (``inputs.headTree`` as the head, ``inputs.requestDigest`` as the build, ``inputs.policyDigest``
as the policy) and the decision the job gave. It is signed with a key made in the test and never
written anywhere but the test's own folder. What these tests show is the verifier: a receipt that is
genuine for one job does not clear another, a receipt not signed by a key the store holds clears
nothing, and an old one clears nothing. The writer and CI attestation are not covered here.

The positive control: the unchanged game's receipt, asked about with that job's own digests, is
cleared by the same command. Without it no row here is held.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.release_gate.common import REPO, GateCase

REPOSITORY = "Expectrail/Expectrail"
CHECK = "player-stays-above-ground"
KID = "release-gate-test-issuer"


def _hex(value: str) -> str:
    """A job's digest as the receipt's bare 64 hex digits (the job may write ``sha256:<hex>``)."""
    text = value.split(":", 1)[1] if ":" in value else value
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise AssertionError(f"not a sha256 digest: {value!r}")
    return text


def _key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    return private, base64.b64encode(private.public_key().public_bytes_raw()).decode("ascii")


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


class ReceiptTest(GateCase):
    """Two real jobs, made once for the class, and a trust store that holds one key."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            import cryptography  # noqa: F401 — trust-check needs it; say so rather than fail obscurely
        except ImportError as exc:
            raise AssertionError(f"the receipt rows need the `trust` extra ({exc}): pip install 'expectrail[trust]'")
        jobs = cls.root / "receipt-jobs"
        cls.clean_job = cls._verify(jobs, cls.clean)
        cls.bug_job = cls._verify(jobs, cls.bug)
        cls.private, cls.public = _key()
        cls.trust_store = cls.root / "trust-store.json"
        cls.trust_store.write_text(json.dumps({"format": "expectrail.trust-store/v1",
                                         "keys": [{"id": KID, "publicKey": cls.public}]}) + "\n", encoding="utf-8")

    @classmethod
    def _verify(cls, jobs: Path, head: Path) -> dict:
        from tests.release_gate.common import GAME, LEASE, ROUTE, SPECS

        done = subprocess.run([sys.executable, "-m", "tests.release_gate.worker", "--jobs-root", str(jobs),
                               "--lease-seconds", LEASE, "verify", "--head", str(head), "--game", GAME,
                               "--routes", ROUTE, "--specs", SPECS, "--json"],
                              cwd=REPO, capture_output=True, text=True, timeout=300)
        status = json.loads(done.stdout)
        status["exitCode"] = done.returncode
        return status

    # --- making a receipt from a job ----------------------------------------------------------------
    def receipt_for(self, job: dict, *, private=None, public: str | None = None, kid: str = KID,
                    issued: datetime | None = None, expires: datetime | None = None, edit=None) -> dict:
        """A receipt for ``job``, signed by ``private`` (the store's key unless given). ``edit`` changes
        the document after it is signed, as someone holding the file could."""
        from expectrail.receipt import sign_receipt

        inputs = job["inputs"]
        now = datetime.now(timezone.utc)
        issued = issued or now - timedelta(minutes=1)
        expires = expires or issued + timedelta(days=1)
        passed = job["decision"] == "accept"
        head = _hex(inputs["headTree"])
        doc = {
            "format": "expectrail.receipt/v1",
            "issuerKeyId": kid,
            "repository": REPOSITORY,
            "baseSha256": head,     # no base: the change is judged by its own approved checks
            "headSha256": head,
            "buildSha256": _hex(inputs["requestDigest"]),
            "policySha256": _hex(inputs["policyDigest"]),
            "routeSetSha256": _hex(inputs["policyDigest"]),
            "versions": {"verifier": job["expectrail"]["version"], "adapter": "godot", "observer": "sam-recorded"},
            "evidence": {"grade": "full", "capabilities": ["frames", "trace"], "artifacts": {"request": _hex(inputs["requestDigest"])}},
            "coverage": {"required": [CHECK], "exercised": [CHECK], "results": {CHECK: "pass" if passed else "fail"}},
            "decision": job["decision"],
            "findings": [],
            "cost": {"usd": 0.0},
            "issuedAt": _stamp(issued),
            "expiresAt": _stamp(expires),
            "algorithm": "ed25519",
            "publicKey": public or self.public,
        }
        doc["signature"] = sign_receipt(doc, private or self.private)
        if edit is not None:
            edit(doc)
        return doc

    def expectations(self, job: dict) -> dict:
        inputs = job["inputs"]
        return {"repo": REPOSITORY, "head": _hex(inputs["headTree"]), "build": _hex(inputs["requestDigest"]),
                "policy": _hex(inputs["policyDigest"])}

    def trust_check(self, receipt: dict, *, store: Path | None = None, **asked) -> tuple[int, str, str]:
        """``python3 -m expectrail.receipt trust-check`` as its own process. ``asked`` names what the
        receipt is asked about (repo, head, build, policy); a value of None leaves that flag out."""
        folder = Path(tempfile.mkdtemp(prefix="receipt-", dir=self.tmp))
        path = folder / "receipt.json"
        path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        argv = [sys.executable, "-m", "expectrail.receipt", "trust-check", str(path),
                "--trust-store", str(store or self.trust_store)]
        for flag, key in (("--repo", "repo"), ("--expect-head", "head"), ("--expect-build", "build"),
                          ("--expect-policy", "policy")):
            if asked.get(key) is not None:
                argv += [flag, asked[key]]
        done = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=60)
        return done.returncode, done.stdout, done.stderr

    def assertNoClearance(self, result: tuple[int, str, str], reason: str) -> None:
        code, out, err = result
        self.assertEqual(code, 1, f"exit {code}: 0 is clearance, 2 is nothing checked\n{out}{err}")
        self.assertIn("\n  clearance: no\n", out)
        self.assertIn(reason, out)

    # --- the positive control -------------------------------------------------------------------------
    def test_control_the_unchanged_games_receipt_is_cleared_for_that_job(self):
        self.assertEqual((self.clean_job["exitCode"], self.clean_job["decision"]), (0, "accept"))
        self.assertEqual((self.bug_job["exitCode"], self.bug_job["decision"]), (1, "reject"))
        code, out, err = self.trust_check(self.receipt_for(self.clean_job), **self.expectations(self.clean_job))
        self.assertEqual(code, 0, out + err)
        self.assertIn("\n  clearance: yes\n", out)

    # --- wrong build or head -------------------------------------------------------------------------
    def test_the_unchanged_games_receipt_does_not_clear_the_seeded_bugs_head(self):
        asked = {**self.expectations(self.clean_job), "head": self.expectations(self.bug_job)["head"]}
        self.assertNotEqual(asked["head"], self.expectations(self.clean_job)["head"])
        self.assertNoClearance(self.trust_check(self.receipt_for(self.clean_job), **asked), "head digest mismatch")

    def test_a_receipt_for_one_build_of_a_head_does_not_clear_another_build_of_it(self):
        # The bug's job is another build; asked about with the unchanged game's head, only the build differs.
        asked = {**self.expectations(self.clean_job), "build": self.expectations(self.bug_job)["build"]}
        self.assertNoClearance(self.trust_check(self.receipt_for(self.clean_job), **asked), "build digest mismatch")

    def test_a_receipt_for_another_repository_does_not_clear_this_one(self):
        asked = {**self.expectations(self.clean_job), "repo": "someone/elsewhere"}
        self.assertNoClearance(self.trust_check(self.receipt_for(self.clean_job), **asked), "repository mismatch")

    def test_a_head_or_build_left_unasked_is_not_a_pass(self):
        for left_out in ("head", "build"):
            with self.subTest(left_out=left_out):
                asked = {**self.expectations(self.clean_job), left_out: None}
                self.assertNoClearance(self.trust_check(self.receipt_for(self.clean_job), **asked),
                                       f"{left_out} not checked")

    # --- unknown signer ------------------------------------------------------------------------------
    def test_a_receipt_signed_by_a_key_the_store_does_not_hold_is_not_cleared(self):
        private, public = _key()
        receipt = self.receipt_for(self.clean_job, private=private, public=public, kid="someone-else")
        self.assertNoClearance(self.trust_check(receipt, **self.expectations(self.clean_job)), "unknown issuer")

    def test_a_receipt_naming_the_trusted_key_id_with_another_key_is_not_cleared(self):
        private, public = _key()
        receipt = self.receipt_for(self.clean_job, private=private, public=public)
        self.assertNoClearance(self.trust_check(receipt, **self.expectations(self.clean_job)),
                               "embedded public key does not match trust store")

    def test_a_receipt_carrying_the_trusted_key_but_signed_by_another_is_not_cleared(self):
        private, _ = _key()
        receipt = self.receipt_for(self.clean_job, private=private)
        self.assertNoClearance(self.trust_check(receipt, **self.expectations(self.clean_job)),
                               "signature does not verify")

    def test_the_seeded_bugs_reject_edited_to_accept_after_signing_is_not_cleared(self):
        def to_accept(doc):
            doc["decision"] = "accept"
            doc["coverage"]["results"][CHECK] = "pass"

        honest = self.receipt_for(self.bug_job)
        self.assertNoClearance(self.trust_check(honest, **self.expectations(self.bug_job)), "not accept")
        edited = self.receipt_for(self.bug_job, edit=to_accept)
        self.assertNoClearance(self.trust_check(edited, **self.expectations(self.bug_job)),
                               "signature does not verify")

    def test_a_store_without_the_signers_key_clears_nothing(self):
        other = self.tmp / "other-store.json"
        _, public = _key()
        other.write_text(json.dumps({"format": "expectrail.trust-store/v1",
                                     "keys": [{"id": "another", "publicKey": public}]}) + "\n", encoding="utf-8")
        self.assertNoClearance(self.trust_check(self.receipt_for(self.clean_job), store=other,
                                                **self.expectations(self.clean_job)), "unknown issuer")

    # --- expired receipt -----------------------------------------------------------------------------
    def test_a_receipt_past_its_expiry_is_not_cleared(self):
        now = datetime.now(timezone.utc)
        receipt = self.receipt_for(self.clean_job, issued=now - timedelta(days=3), expires=now - timedelta(days=1))
        self.assertNoClearance(self.trust_check(receipt, **self.expectations(self.clean_job)), "stale or not-yet-valid")

    def test_a_receipt_issued_in_the_future_is_not_cleared(self):
        now = datetime.now(timezone.utc)
        receipt = self.receipt_for(self.clean_job, issued=now + timedelta(hours=1), expires=now + timedelta(days=1))
        self.assertNoClearance(self.trust_check(receipt, **self.expectations(self.clean_job)), "stale or not-yet-valid")

    def test_a_receipt_valid_for_longer_than_seven_days_is_not_cleared(self):
        now = datetime.now(timezone.utc)
        receipt = self.receipt_for(self.clean_job, issued=now - timedelta(days=1), expires=now + timedelta(days=7))
        self.assertNoClearance(self.trust_check(receipt, **self.expectations(self.clean_job)), "longer than 7 days")

    def test_an_expired_receipt_with_its_dates_edited_after_signing_is_not_cleared(self):
        now = datetime.now(timezone.utc)

        def extend(doc):
            doc["expiresAt"] = _stamp(now + timedelta(days=1))

        receipt = self.receipt_for(self.clean_job, issued=now - timedelta(days=3), expires=now - timedelta(days=1),
                                   edit=extend)
        self.assertNoClearance(self.trust_check(receipt, **self.expectations(self.clean_job)),
                               "signature does not verify")
