"""Receipt v1: writer, reader, Ed25519 signing and offline trust-store verification.

A receipt is a signed statement of what was checked, on which build, under which
policy, and what the decision was. The signature is over the canonical JSON of
the receipt with the ``signature`` field omitted. Verification never trusts a
public key found only inside the receipt; the key must be in a trust store the
verifier already holds.

    python -m expectrail.receipt trust-check RECEIPT [--repo OWNER/NAME] \\
        [--trust-store FILE] [--expect-head SHA] [--expect-policy DIGEST]

Tests generate throwaway keys. Never put a real key in a file.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from expectrail.contracts import (
    ContractError,
    canonical_v1,
    strict_loads,
)

import jsonschema

SCHEMAS = Path(__file__).resolve().parent.parent / "contracts"
RECEIPT_SCHEMA = json.loads((SCHEMAS / "receipt.v1.schema.json").read_text(encoding="utf-8"))


def _validate_receipt(doc: dict) -> None:
    """Validate a receipt against its schema. Refuses non-finite numbers via canonical_v1."""
    canonical_v1(doc)
    errors = sorted(
        jsonschema.Draft202012Validator(RECEIPT_SCHEMA).iter_errors(doc),
        key=lambda e: list(e.path),
    )
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.path) or "(root)"
        raise ContractError(f"receipt: {where}: {first.message}")
    if doc.get("format") != FORMAT:
        raise ContractError(f"expected {FORMAT}, got {doc.get('format')!r}")


FORMAT = "expectrail.receipt/v1"
ALGORITHM = "ed25519"
TRUST_STORE_FORMAT = "expectrail.trust-store/v1"


class ReceiptError(ContractError):
    """Raised when a receipt cannot be written, read or verified."""


def _canonical_body(doc: dict) -> bytes:
    """Canonical bytes of the receipt with the signature field removed."""
    body = {k: v for k, v in doc.items() if k != "signature"}
    return canonical_v1(body)


def sign_receipt(doc: dict, private_key: Ed25519PrivateKey) -> str:
    """Sign the canonical body and return the base64 signature."""
    payload = _canonical_body(doc)
    sig = private_key.sign(payload)
    return base64.b64encode(sig).decode("ascii")


def verify_signature(doc: dict, public_key_b64: str) -> bool:
    """True if the signature verifies with the given public key."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        pub.verify(base64.b64decode(doc["signature"]), _canonical_body(doc))
        return True
    except Exception:  # noqa: BLE001 — any crypto failure is a failed verify
        return False


def write_receipt(doc: dict, private_key: Ed25519PrivateKey, path: Path | None = None) -> dict:
    """Validate, sign and optionally write a receipt. Returns the signed document.

    ``doc`` must contain every field except ``signature``. The signature is
    computed and inserted. The private key is never written.
    """
    if "signature" in doc:
        raise ReceiptError("receipt to sign must not already contain a signature")
    # Placeholder so validation can run; replaced after.
    candidate = dict(doc)
    candidate["signature"] = "pending"
    _validate_receipt(candidate)
    signature = sign_receipt(candidate, private_key)
    signed = dict(candidate)
    signed["signature"] = signature
    # Re-validate the final document.
    _validate_receipt(signed)
    if path is not None:
        path.write_text(json.dumps(signed, indent=2) + "\n", encoding="utf-8")
    return signed


def read_receipt(path: Path) -> dict:
    """Load and schema-validate a receipt. Does not check the signature."""
    doc = strict_loads(path.read_text(encoding="utf-8"))
    _validate_receipt(doc)
    return doc


def load_trust_store(path: Path) -> dict[str, str]:
    """Load a trust store. Returns {key_id: public_key_b64}.

    Format: {"format": "expectrail.trust-store/v1", "keys": [{"id": "...", "publicKey": "..."}]}
    """
    text = path.read_text(encoding="utf-8")
    doc = strict_loads(text)
    if not isinstance(doc, dict) or doc.get("format") != TRUST_STORE_FORMAT:
        raise ReceiptError(f"trust store must be {TRUST_STORE_FORMAT}")
    keys = doc.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ReceiptError("trust store must contain a non-empty keys list")
    out: dict[str, str] = {}
    for entry in keys:
        if not isinstance(entry, dict):
            raise ReceiptError("trust-store key entry must be an object")
        kid = entry.get("id")
        pub = entry.get("publicKey")
        if not isinstance(kid, str) or not kid or not isinstance(pub, str) or not pub:
            raise ReceiptError("trust-store key entry needs id and publicKey")
        if kid in out:
            raise ReceiptError(f"duplicate key id in trust store: {kid}")
        # Reject a key that is only the embedded one by requiring it is listed here.
        out[kid] = pub
    return out


def check_receipt(
    doc: dict,
    trust_store: dict[str, str],
    *,
    expect_repo: str | None = None,
    expect_head: str | None = None,
    expect_policy: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify signature, issuer, identity, policy, freshness and completeness.

    Returns a report dict. A valid signature on insufficient evidence still
    reports ``clearance: false`` with reason ``"no clearance"``.
    """
    now = now or datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "format": FORMAT,
        "valid_signature": False,
        "known_issuer": False,
        "identity_ok": False,
        "policy_ok": False,
        "fresh": False,
        "complete": False,
        "clearance": False,
        "decision": doc.get("decision"),
        "establishes": [],
        "does_not_establish": [],
        "reasons": [],
    }

    kid = doc.get("issuerKeyId")
    embedded_pub = doc.get("publicKey")
    trusted_pub = trust_store.get(kid) if isinstance(kid, str) else None

    if trusted_pub is None:
        report["reasons"].append("unknown issuer (key id not in trust store)")
        report["does_not_establish"].append("issuer identity")
    elif trusted_pub != embedded_pub:
        report["reasons"].append("embedded public key does not match trust store")
        report["does_not_establish"].append("issuer identity")
    else:
        report["known_issuer"] = True
        if verify_signature(doc, trusted_pub):
            report["valid_signature"] = True
            report["establishes"].append(f"signed by known issuer {kid}")
        else:
            report["reasons"].append("signature does not verify with trusted key")
            report["does_not_establish"].append("signature")

    # Identity
    repo_ok = expect_repo is None or doc.get("repository") == expect_repo
    head_ok = expect_head is None or doc.get("headSha256") == expect_head
    if not repo_ok:
        report["reasons"].append(f"repository mismatch: got {doc.get('repository')!r}, expected {expect_repo!r}")
    if not head_ok:
        report["reasons"].append("head digest mismatch")
    report["identity_ok"] = repo_ok and head_ok and report["valid_signature"]
    if report["identity_ok"]:
        report["establishes"].append(f"repository {doc.get('repository')} head {doc.get('headSha256', '')[:12]}…")
    else:
        report["does_not_establish"].append("build identity")

    # Policy
    policy_ok = expect_policy is None or doc.get("policySha256") == expect_policy
    if not policy_ok:
        report["reasons"].append("policy digest mismatch")
    report["policy_ok"] = policy_ok
    if policy_ok and report["valid_signature"]:
        report["establishes"].append("policy digest matches expectation")
    else:
        report["does_not_establish"].append("policy binding")

    # Freshness
    try:
        expires = datetime.fromisoformat(doc["expiresAt"].replace("Z", "+00:00"))
        issued = datetime.fromisoformat(doc["issuedAt"].replace("Z", "+00:00"))
        fresh = issued <= now < expires
    except Exception:  # noqa: BLE001
        fresh = False
        report["reasons"].append("unparseable timestamps")
    if not fresh:
        report["reasons"].append("stale or not-yet-valid receipt")
    report["fresh"] = fresh
    if fresh:
        report["establishes"].append("within issuedAt..expiresAt")
    else:
        report["does_not_establish"].append("freshness")

    # Completeness: every required check is exercised and has a result.
    coverage = doc.get("coverage") or {}
    required = set(coverage.get("required") or [])
    exercised = set(coverage.get("exercised") or [])
    results = coverage.get("results") or {}
    missing = required - exercised
    incomplete_results = required - set(results)
    grade = (doc.get("evidence") or {}).get("grade")
    complete = not missing and not incomplete_results and grade == "full"
    if missing:
        report["reasons"].append(f"removed or missing required checks: {sorted(missing)}")
    if incomplete_results:
        report["reasons"].append(f"required checks without results: {sorted(incomplete_results)}")
    if grade != "full":
        report["reasons"].append(f"evidence grade is {grade!r}, not full")
    report["complete"] = complete
    if complete:
        report["establishes"].append("all required checks exercised with full evidence")
    else:
        report["does_not_establish"].append("completeness of evidence")

    # Clearance only if everything holds and the decision is accept on full evidence.
    # A valid signature on insufficient evidence still reports no clearance.
    if (
        report["valid_signature"]
        and report["known_issuer"]
        and report["identity_ok"]
        and report["policy_ok"]
        and report["fresh"]
        and report["complete"]
        and doc.get("decision") == "accept"
    ):
        report["clearance"] = True
        report["establishes"].append("clearance: accept on full evidence")
    else:
        report["clearance"] = False
        report["does_not_establish"].append("clearance")
        if report["valid_signature"] and not report["complete"]:
            report["reasons"].append("no clearance")

    return report


def _print_report(report: dict) -> None:
    print(f"Receipt: {report['format']}")
    print(f"  signature: {'valid' if report['valid_signature'] else 'INVALID'}")
    print(f"  issuer: {'known' if report['known_issuer'] else 'UNKNOWN'}")
    print(f"  identity: {'ok' if report['identity_ok'] else 'mismatch'}")
    print(f"  policy: {'ok' if report['policy_ok'] else 'mismatch'}")
    print(f"  fresh: {'yes' if report['fresh'] else 'no'}")
    print(f"  complete: {'yes' if report['complete'] else 'no'}")
    print(f"  decision: {report['decision']}")
    print(f"  clearance: {'yes' if report['clearance'] else 'no'}")
    if report["establishes"]:
        print("  establishes:")
        for line in report["establishes"]:
            print(f"    - {line}")
    if report["does_not_establish"]:
        print("  does not establish:")
        for line in report["does_not_establish"]:
            print(f"    - {line}")
    if report["reasons"]:
        print("  reasons:")
        for line in report["reasons"]:
            print(f"    - {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="expectrail.receipt")
    sub = parser.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("trust-check", help="verify a receipt against a trust store")
    check.add_argument("receipt", type=Path)
    check.add_argument("--repo", default=None, help="OWNER/NAME the receipt must be about")
    check.add_argument("--trust-store", type=Path, required=True)
    check.add_argument("--expect-head", default=None)
    check.add_argument("--expect-policy", default=None)

    args = parser.parse_args(argv)
    if args.cmd == "trust-check":
        try:
            doc = read_receipt(args.receipt)
            store = load_trust_store(args.trust_store)
            report = check_receipt(
                doc,
                store,
                expect_repo=args.repo,
                expect_head=args.expect_head,
                expect_policy=args.expect_policy,
            )
        except (ContractError, ReceiptError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        _print_report(report)
        return 0 if report["clearance"] else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
