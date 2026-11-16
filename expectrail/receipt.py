"""Receipt v1: writer, reader, Ed25519 signing and offline trust-store verification.

A receipt is a signed statement of what was checked, on which build, under which
policy, and what the decision was. The signature is over the canonical JSON of
the receipt with the ``signature`` field omitted. Verification never trusts a
public key found only inside the receipt; the key must be in a trust store the
verifier already holds.

    expectrail trust-check RECEIPT --trust-store FILE \\
        [--repo OWNER/NAME] [--expect-head SHA] [--expect-build DIGEST] [--expect-policy DIGEST]

``python -m expectrail.receipt trust-check ...`` is the same check. The two differ only in the exit
code for a receipt or trust store that cannot be read, or a command line that cannot: 5 from
``expectrail`` (as every ``expectrail`` command), 2 from ``python -m expectrail.receipt`` (as it was
first built). Clearance is 0 and no clearance is 1 from both. Installed from the wheel, this module
needs the ``trust`` extra (``cryptography`` and ``jsonschema``); without it ``expectrail trust-check``
says what to install and checks nothing.

Clearance is an allow-list. It is granted only when every condition was positively
shown: a known issuer, a valid signature, repository, head, build and policy each
given and matched, a validity of at most 7 days that contains now, at least one required
check, every required check's result ``pass``, and ``exercised`` covering
``required``, on full evidence, with decision ``accept``. Anything not shown is
listed under ``does_not_establish`` and clearance is refused. A valid signature
on insufficient evidence still reports "no clearance".

Trust stores come in two formats. ``expectrail.trust-store/v1`` lists keys with no dates: each key
is trusted for any receipt it signed. ``expectrail.trust-store/v2`` gives each key the span it may
sign in: ``validFrom``, an optional ``notAfter`` (the key was retired: a receipt it says it issued at
or after that time is refused) and an optional ``revoked`` (the key may be in someone else's hands:
every receipt it signed is refused, whatever date the receipt carries, since whoever holds the key
can write any date). The person who holds the keys edits a store with

    python -m expectrail.receipt trust-store add|retire|revoke|show STORE ...

which writes public material only. ``docs/trust-store.md`` says where Expectrail's store is
published and how a key is rotated.

Tests generate throwaway keys. Never put a real key in a file.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import hashlib
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from expectrail import resources
from expectrail.contracts import (
    ContractError,
    canonical_v1,
    strict_loads,
)

import jsonschema

# The schemas beside the package in a clone, inside it (``_bundle``) in an installed copy.
SCHEMAS = resources.ROOT / "contracts"
RECEIPT_SCHEMA = json.loads((SCHEMAS / "receipt.v1.schema.json").read_text(encoding="utf-8"))


# Canonical base64 of an Ed25519 signature (64 bytes) and public key (32 bytes): the only
# spelling each value has. Padded, nothing outside the alphabet, and the unused bits of the last
# character zero, so no two strings decode to the same bytes. Matched with fullmatch, so a trailing
# newline is refused too (a schema ``pattern`` read by jsonschema lets ``$`` match before one).
SIGNATURE_RE = re.compile(r"[A-Za-z0-9+/]{85}[AQgw]==")
PUBLIC_KEY_RE = re.compile(r"[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=")
# RFC 3339 with an offset: the one timestamp form the writer emits, and the form the browser check
# on docs/verify/ reads. Python's fromisoformat reads more (a space, no offset); the writer does not.
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
                          re.ASCII)
# Stands in for the signature while the writer validates the unsigned document.
_PLACEHOLDER_SIGNATURE = "A" * 86 + "=="


def strict_b64(value: str, pattern: re.Pattern, what: str) -> bytes:
    """Decode canonical base64 only. Anything else is refused, never read leniently."""
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ContractError(f"{what} is not canonical base64")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:  # unreachable after the pattern; kept as the fallback
        raise ContractError(f"{what} is not canonical base64") from exc
    if base64.b64encode(raw).decode("ascii") != value:
        raise ContractError(f"{what} is not canonical base64")
    return raw


def check_timestamp(value: object, what: str) -> datetime:
    """An RFC 3339 date-time with an offset, as the writer must emit it."""
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        raise ContractError(f"receipt: {what}: {value!r} is not an RFC 3339 date-time with an offset")
    try:
        parsed = _parse_time(value)
    except ValueError as exc:
        raise ContractError(f"receipt: {what}: {value!r} is not a real date and time") from exc
    if parsed.tzinfo is None:  # the pattern requires an offset; kept as the fallback
        raise ContractError(f"receipt: {what}: {value!r} has no offset")
    return parsed


def _validate_receipt(doc: dict) -> None:
    """Validate a receipt against its schema. Refuses non-finite numbers via canonical_v1.

    The signature and the public key must be canonical base64 of the right length.
    """
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
    strict_b64(doc["signature"], SIGNATURE_RE, "receipt: signature")
    strict_b64(doc["publicKey"], PUBLIC_KEY_RE, "receipt: publicKey")


FORMAT = "expectrail.receipt/v1"
ALGORITHM = "ed25519"
TRUST_STORE_FORMAT = "expectrail.trust-store/v1"
TRUST_STORE_V2 = "expectrail.trust-store/v2"
TRUST_STORE_FORMATS = (TRUST_STORE_FORMAT, TRUST_STORE_V2)
MAX_VALIDITY = timedelta(days=7)
# The fields a key entry may have in each format. Anything else refuses the store: a v1 reader that
# skipped a ``revoked`` it did not know would trust the key it was meant to stop trusting.
_V1_KEY_FIELDS = frozenset({"id", "publicKey", "note"})
_V2_KEY_FIELDS = frozenset({"id", "publicKey", "note", "validFrom", "notAfter", "revoked"})
_V2_STORE_FIELDS = frozenset({"format", "keys", "note"})


@dataclass(frozen=True)
class TrustKey:
    """One issuer key from a trust store, with the span it may sign in (v2) or none (v1)."""

    public_key: str
    valid_from: str | None = None
    not_after: str | None = None
    revoked_at: str | None = None
    revoked_reason: str | None = None

    @property
    def has_window(self) -> bool:
        return self.valid_from is not None


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
        pub = Ed25519PublicKey.from_public_bytes(strict_b64(public_key_b64, PUBLIC_KEY_RE, "public key"))
        pub.verify(strict_b64(doc["signature"], SIGNATURE_RE, "signature"), _canonical_body(doc))
        return True
    except Exception:  # noqa: BLE001 — any crypto failure is a failed verify
        return False


def write_receipt(doc: dict, private_key: Ed25519PrivateKey, path: Path | None = None) -> dict:
    """Validate, sign and optionally write a receipt. Returns the signed document.

    ``doc`` must contain every field except ``signature``. The signature is
    computed and inserted. The private key is never written. ``issuedAt`` and
    ``expiresAt`` must be RFC 3339 date-times with an offset: the schema's
    ``format: date-time`` is not enforced by jsonschema without a format checker,
    so the writer checks it itself.
    """
    if "signature" in doc:
        raise ReceiptError("receipt to sign must not already contain a signature")
    # Placeholder so validation can run; replaced after.
    candidate = dict(doc)
    candidate["signature"] = _PLACEHOLDER_SIGNATURE
    _validate_receipt(candidate)
    check_timestamp(candidate.get("issuedAt"), "issuedAt")
    check_timestamp(candidate.get("expiresAt"), "expiresAt")
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


def load_trust_store(path: Path) -> dict[str, TrustKey]:
    """Load a trust store. Returns {key_id: TrustKey}.

    v1: {"format": "expectrail.trust-store/v1", "keys": [{"id": "...", "publicKey": "..."}]}
    v2: as v1, and each key has "validFrom", and may have "notAfter" and "revoked": {"at", "reason"}
    (contracts/trust-store.v2.schema.json).
    """
    return parse_trust_store(path.read_text(encoding="utf-8"))


def _store_time(value: object, where: str) -> datetime:
    """A trust store's date: RFC 3339 with an offset, a real date. Anything else refuses the store."""
    try:
        return check_timestamp(value, where)
    except ContractError as exc:
        raise ReceiptError(f"trust store: {where}: {value!r} is not an RFC 3339 date-time with an offset") from exc


def parse_trust_store(text: str) -> dict[str, TrustKey]:
    """Read a trust store's text. Each public key must be canonical base64 of 32 bytes.

    Anything this reader does not understand refuses the whole store, so nothing is trusted by a
    reader that skipped a field: an unknown format, an unknown field on a key, a v2 date that is not
    RFC 3339, a ``notAfter`` that is not after ``validFrom``.
    """
    doc = strict_loads(text)
    if not isinstance(doc, dict) or doc.get("format") not in TRUST_STORE_FORMATS:
        raise ReceiptError(f"trust store must be {TRUST_STORE_FORMAT} or {TRUST_STORE_V2}")
    v2 = doc["format"] == TRUST_STORE_V2
    if v2:
        extra = sorted(set(doc) - _V2_STORE_FIELDS)
        if extra:
            raise ReceiptError(f"trust store: {extra[0]!r} is not a field of {TRUST_STORE_V2}")
        if "note" in doc and not isinstance(doc["note"], str):
            raise ReceiptError("trust store: note must be a string")
    keys = doc.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ReceiptError("trust store must contain a non-empty keys list")
    out: dict[str, TrustKey] = {}
    for entry in keys:
        if not isinstance(entry, dict):
            raise ReceiptError("trust-store key entry must be an object")
        kid = entry.get("id")
        pub = entry.get("publicKey")
        if not isinstance(kid, str) or not kid or not isinstance(pub, str) or not pub:
            raise ReceiptError("trust-store key entry needs id and publicKey")
        if kid in out:
            raise ReceiptError(f"duplicate key id in trust store: {kid}")
        if not PUBLIC_KEY_RE.fullmatch(pub):
            raise ReceiptError(f"trust-store key {kid}: publicKey is not canonical base64 of a 32-byte Ed25519 key")
        allowed = _V2_KEY_FIELDS if v2 else _V1_KEY_FIELDS
        extra = sorted(set(entry) - allowed)
        if extra:
            hint = "" if v2 else f" (validity and revocation need {TRUST_STORE_V2})"
            raise ReceiptError(f"trust-store key {kid}: {extra[0]!r} is not a field of {doc['format']}{hint}")
        if "note" in entry and not isinstance(entry["note"], str):
            raise ReceiptError(f"trust-store key {kid}: note must be a string")
        if not v2:
            # Reject a key that is only the embedded one by requiring it is listed here.
            out[kid] = TrustKey(pub)
            continue
        if "validFrom" not in entry:
            raise ReceiptError(f"trust-store key {kid}: validFrom is missing")
        start = _store_time(entry["validFrom"], f"key {kid}: validFrom")
        not_after = entry.get("notAfter")
        if "notAfter" in entry and _store_time(not_after, f"key {kid}: notAfter") <= start:
            raise ReceiptError(f"trust-store key {kid}: notAfter must be after validFrom")
        revoked_at = revoked_reason = None
        if "revoked" in entry:
            revoked = entry["revoked"]
            if not isinstance(revoked, dict) or set(revoked) != {"at", "reason"}:
                raise ReceiptError(f"trust-store key {kid}: revoked must be {{\"at\", \"reason\"}} and nothing else")
            _store_time(revoked["at"], f"key {kid}: revoked/at")
            if not isinstance(revoked["reason"], str) or not revoked["reason"]:
                raise ReceiptError(f"trust-store key {kid}: revoked/reason must be a non-empty string")
            revoked_at, revoked_reason = revoked["at"], revoked["reason"]
        out[kid] = TrustKey(pub, entry["validFrom"], not_after, revoked_at, revoked_reason)
    return out


def _as_trust_key(value: object) -> TrustKey | None:
    """A store built in code may map key ids to plain public keys: those are v1 keys, with no dates."""
    if value is None or isinstance(value, TrustKey):
        return value
    if isinstance(value, str):
        return TrustKey(value)
    return None


def _issued_within(doc: dict, key: TrustKey) -> bool:
    """True when the receipt says it was issued inside the key's span. An unreadable time is outside."""
    try:
        issued = check_timestamp(doc.get("issuedAt"), "issuedAt")
    except ContractError:
        return False
    if issued < _parse_time(key.valid_from):
        return False
    return key.not_after is None or issued < _parse_time(key.not_after)


def key_window_reason(key: TrustKey) -> str:
    return f"receipt issued outside the issuer key's validity ({key.valid_from} to {key.not_after or 'no end'})"


def revoked_reason(key: TrustKey) -> str:
    return f"issuer key revoked at {key.revoked_at}: {key.revoked_reason}"


_IDENTITY_NOT_CHECKED = ("repository not checked", "head not checked", "build not checked")


def _gap(report: dict, reason: str, gap: str | None = None) -> None:
    """Record something that was not positively shown. The same line is not added twice."""
    if reason not in report["reasons"]:
        report["reasons"].append(reason)
    item = gap if gap is not None else reason
    if item not in report["does_not_establish"]:
        report["does_not_establish"].append(item)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_receipt(
    doc: dict,
    trust_store: dict[str, TrustKey] | dict[str, str],
    *,
    expect_repo: str | None = None,
    expect_head: str | None = None,
    expect_policy: str | None = None,
    now: datetime | None = None,
    expect_build: str | None = None,
) -> dict[str, Any]:
    """Verify signature, issuer, identity, policy, freshness and completeness.

    Clearance is granted only when every condition was positively shown. A missing
    ``--repo``, ``--expect-head``, ``--expect-build`` or ``--expect-policy`` is
    "not checked", not a pass. The build is part of identity: a genuine receipt for
    one build of a head does not clear another build of the same head. A required check passes only when its result is ``"pass"``. The span
    from ``issuedAt`` to ``expiresAt`` must be positive and at most 7 days.
    A valid signature on insufficient evidence still reports ``"no clearance"``.

    A v2 store's key is a known issuer only when it is not revoked and the receipt's ``issuedAt``
    falls in ``validFrom`` (inclusive) to ``notAfter`` (exclusive). A revoked key is refused for every
    receipt: whoever holds a stolen key can write any ``issuedAt``. Since a receipt is valid for at
    most 7 days, a retired key's receipts stop clearing 7 days after its ``notAfter`` at the latest.
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
    trusted = _as_trust_key(trust_store.get(kid)) if isinstance(kid, str) else None

    if trusted is None:
        report["reasons"].append("unknown issuer (key id not in trust store)")
        report["does_not_establish"].append("issuer identity")
    elif trusted.public_key != embedded_pub:
        report["reasons"].append("embedded public key does not match trust store")
        report["does_not_establish"].append("issuer identity")
    elif trusted.revoked_at is not None:
        report["reasons"].append(revoked_reason(trusted))
        report["does_not_establish"].append("issuer identity")
    elif trusted.has_window and not _issued_within(doc, trusted):
        report["reasons"].append(key_window_reason(trusted))
        report["does_not_establish"].append("issuer identity")
    else:
        report["known_issuer"] = True
        if verify_signature(doc, trusted.public_key):
            report["valid_signature"] = True
            report["establishes"].append(f"signed by known issuer {kid}")
        else:
            report["reasons"].append("signature does not verify with trusted key")
            report["does_not_establish"].append("signature")

    # Identity and policy are shown only when the caller asked and the receipt matches.
    # Omitting the question is not a pass.
    repo_shown = expect_repo is not None and doc.get("repository") == expect_repo
    head_shown = expect_head is not None and doc.get("headSha256") == expect_head
    build_shown = expect_build is not None and doc.get("buildSha256") == expect_build
    policy_shown = expect_policy is not None and doc.get("policySha256") == expect_policy
    if expect_repo is None:
        _gap(report, "repository not checked")
    elif doc.get("repository") != expect_repo:
        _gap(report, f"repository mismatch: got {doc.get('repository')!r}, expected {expect_repo!r}",
             "build identity")
    if expect_head is None:
        _gap(report, "head not checked")
    elif doc.get("headSha256") != expect_head:
        _gap(report, "head digest mismatch", "build identity")
    if expect_build is None:
        _gap(report, "build not checked")
    elif doc.get("buildSha256") != expect_build:
        _gap(report, "build digest mismatch", "build identity")
    report["identity_ok"] = bool(report["valid_signature"] and repo_shown and head_shown and build_shown)
    if report["identity_ok"]:
        report["establishes"].append(f"repository {doc.get('repository')} head {doc.get('headSha256', '')[:12]}… "
                                     f"build {doc.get('buildSha256', '')[:12]}…")
    elif "build identity" not in report["does_not_establish"] and any(
            item in report["does_not_establish"] for item in _IDENTITY_NOT_CHECKED):
        report["does_not_establish"].append("build identity")

    if expect_policy is None:
        _gap(report, "policy not checked")
    elif doc.get("policySha256") != expect_policy:
        _gap(report, "policy digest mismatch", "policy binding")
    report["policy_ok"] = policy_shown
    if policy_shown and report["valid_signature"]:
        report["establishes"].append("policy digest matches expectation")
    elif not policy_shown and "policy binding" not in report["does_not_establish"]:
        report["does_not_establish"].append("policy binding")

    # Freshness: now is inside the window, and the window is at most 7 days.
    try:
        expires = _parse_time(doc["expiresAt"])
        issued = _parse_time(doc["issuedAt"])
        span = expires - issued
        in_window = issued <= now < expires
        bounded = timedelta(0) < span <= MAX_VALIDITY
    except Exception:  # noqa: BLE001 — a bad timestamp is not a shown window
        in_window = False
        bounded = False
        span = None
        _gap(report, "unparseable timestamps", "freshness")
    if not in_window:
        _gap(report, "stale or not-yet-valid receipt", "freshness")
    if not bounded:
        if span is not None and span > MAX_VALIDITY:
            _gap(report, "validity longer than 7 days", "validity within 7 days")
        else:
            _gap(report, "validity is not a positive span of at most 7 days", "validity within 7 days")
    report["fresh"] = bool(in_window and bounded)
    if report["fresh"]:
        report["establishes"].append("within issuedAt..expiresAt, at most 7 days")
    else:
        _gap(report, "freshness")

    # Completeness: at least one required check, each result is pass, exercised covers required.
    coverage = doc.get("coverage") or {}
    required = list(coverage.get("required") or [])
    required_set = set(required)
    exercised = set(coverage.get("exercised") or [])
    results = coverage.get("results") or {}
    grade = (doc.get("evidence") or {}).get("grade")
    if not required_set:
        _gap(report, "no required checks", "at least one required check")
    missing = required_set - exercised
    if missing:
        _gap(report, f"removed or missing required checks: {sorted(missing)}", "exercised covers required")
    failed = []
    for name in sorted(required_set):
        value = results.get(name)
        if value != "pass":
            failed.append(name)
            _gap(report, f"required check {name!r} is {value!r}, not pass", "every required check passed")
    if grade != "full":
        _gap(report, f"evidence grade is {grade!r}, not full", "full evidence")
    report["complete"] = bool(required_set) and not missing and not failed and grade == "full"
    if report["complete"]:
        report["establishes"].append("all required checks passed, exercised, on full evidence")
    else:
        _gap(report, "completeness of evidence")

    if doc.get("decision") != "accept":
        _gap(report, f"decision is {doc.get('decision')!r}, not accept", "decision accept")

    # Allow-list: every condition above was shown. Nothing missing is filled in as a pass.
    report["clearance"] = bool(
        report["valid_signature"]
        and report["known_issuer"]
        and repo_shown
        and head_shown
        and build_shown
        and policy_shown
        and report["fresh"]
        and report["complete"]
        and doc.get("decision") == "accept"
    )
    if report["clearance"]:
        report["establishes"].append("clearance: accept on full evidence")
    else:
        _gap(report, "clearance")
        if report["valid_signature"]:
            _gap(report, "no clearance", "clearance")
    return report


_IDENTITY_MISMATCH = ("repository mismatch", "head digest mismatch", "build digest mismatch")


def issuer_word(report: dict) -> str:
    """The issuer line: known, or why not. A revoked or out-of-date key is in the store, not unknown."""
    if report["known_issuer"]:
        return "known"
    if any(line.startswith("issuer key revoked at ") for line in report["reasons"]):
        return "REVOKED (in the trust store, revoked)"
    if any(line.startswith("receipt issued outside the issuer key's validity") for line in report["reasons"]):
        return "NOT FOR THIS DATE (in the trust store, not valid when the receipt says it was issued)"
    return "UNKNOWN"


def _print_report(report: dict) -> None:
    def identity_word() -> str:
        if any(item in report["does_not_establish"] for item in _IDENTITY_NOT_CHECKED):
            return "not checked"
        if report["identity_ok"]:
            return "ok"
        if any(line.startswith(_IDENTITY_MISMATCH) for line in report["reasons"]):
            return "mismatch"
        # Everything asked matched, but nothing a trusted key signed says so.
        return "not shown (no valid signature from a trusted key)"

    def policy_word() -> str:
        if "policy not checked" in report["does_not_establish"]:
            return "not checked"
        return "ok" if report["policy_ok"] else "mismatch"

    print(f"Receipt: {report['format']}")
    print(f"  signature: {'valid' if report['valid_signature'] else 'INVALID'}")
    print(f"  issuer: {issuer_word(report)}")
    print(f"  identity: {identity_word()}")
    print(f"  policy: {policy_word()}")
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


class _UsageError(Exception):
    """A command line that cannot be read. Raised instead of argparse's exit, so the caller picks the code."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # noqa: D401 — argparse's hook
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise _UsageError(message)


def _trust_check_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--repo", default=None, help="OWNER/NAME the receipt must be about")
    parser.add_argument("--trust-store", type=Path, required=True)
    parser.add_argument("--expect-head", default=None)
    parser.add_argument("--expect-build", default=None, help="buildSha256 the receipt must name")
    parser.add_argument("--expect-policy", default=None)


def _trust_check(args: argparse.Namespace, error_code: int) -> int:
    try:
        doc = read_receipt(args.receipt)
        store = load_trust_store(args.trust_store)
        report = check_receipt(
            doc,
            store,
            expect_repo=args.repo,
            expect_head=args.expect_head,
            expect_build=args.expect_build,
            expect_policy=args.expect_policy,
        )
    except (ContractError, ReceiptError, OSError, ValueError) as exc:
        # ValueError covers a file that is not UTF-8 text. Nothing was checked: no report is printed.
        print(f"error: {exc}. Nothing was checked.", file=sys.stderr)
        return error_code
    _print_report(report)
    return 0 if report["clearance"] else 1


def trust_check_main(argv: list[str] | None = None, *, prog: str = "expectrail trust-check",
                     error_code: int = 5) -> int:
    """``expectrail trust-check``: 0 clearance, 1 no clearance, ``error_code`` when nothing could be checked."""
    parser = _Parser(prog=prog, description="Verify a receipt against a trust store you already hold, and say "
                     "what it does and does not establish. Exit 0: clearance. 1: no clearance. "
                     f"{error_code}: nothing was checked (the receipt, the trust store or the command line could not be read).")
    _trust_check_options(parser)
    try:
        args = parser.parse_args(argv)
    except _UsageError:
        print("Nothing was checked.", file=sys.stderr)
        return error_code
    return _trust_check(args, error_code)


# ---- editing a v2 trust store (public material only) ----

def _now_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_v2_for_edit(path: Path, *, create: bool) -> dict:
    """The store as a document, read through parse_trust_store first so nothing unreadable is edited."""
    if not path.exists():
        if create:
            return {"format": TRUST_STORE_V2, "keys": []}
        raise ReceiptError(f"{path}: no such trust store")
    text = path.read_text(encoding="utf-8")
    parse_trust_store(text)
    doc = strict_loads(text)
    if doc["format"] != TRUST_STORE_V2:
        raise ReceiptError(f"{path} is {doc['format']}: retiring and revoking need {TRUST_STORE_V2}. Start a new v2 "
                           "store and add each key with the date it began signing.")
    return doc


def _write_store(path: Path, doc: dict) -> str:
    """Write atomically, after reading the result back through the same reader trust-check uses."""
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    parse_trust_store(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".trust-store-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entry(doc: dict, kid: str) -> dict:
    for entry in doc["keys"]:
        if entry["id"] == kid:
            return entry
    raise ReceiptError(f"no key {kid!r} in this trust store")


def store_add(path: Path, kid: str, public_key: str, valid_from: str | None = None) -> str:
    """Add an issuer's public key, trusted for receipts issued from ``valid_from`` (default now)."""
    doc = _read_v2_for_edit(path, create=True)
    if any(entry["id"] == kid for entry in doc["keys"]):
        raise ReceiptError(f"key {kid!r} is already in this trust store; a new key needs a new id")
    if any(entry["publicKey"] == public_key for entry in doc["keys"]):
        raise ReceiptError("this public key is already in the trust store under another id")
    doc["keys"].append({"id": kid, "publicKey": public_key, "validFrom": valid_from or _now_stamp()})
    return _write_store(path, doc)


def store_retire(path: Path, kid: str, at: str | None = None) -> str:
    """Stop trusting a key for receipts issued at or after ``at`` (default now). Earlier receipts
    stay checkable until they expire, at most 7 days later."""
    doc = _read_v2_for_edit(path, create=False)
    entry = _entry(doc, kid)
    if "notAfter" in entry:
        raise ReceiptError(f"key {kid!r} was already retired at {entry['notAfter']}")
    entry["notAfter"] = at or _now_stamp()
    return _write_store(path, doc)


def store_revoke(path: Path, kid: str, reason: str, at: str | None = None) -> str:
    """Stop trusting a key for every receipt, whatever date it carries."""
    doc = _read_v2_for_edit(path, create=False)
    entry = _entry(doc, kid)
    if "revoked" in entry:
        raise ReceiptError(f"key {kid!r} was already revoked at {entry['revoked']['at']}")
    entry["revoked"] = {"at": at or _now_stamp(), "reason": reason}
    return _write_store(path, doc)


def key_state(key: TrustKey, now: datetime | None = None) -> str:
    """One line on what a key is trusted for now, in the words trust-check uses."""
    now = now or datetime.now(timezone.utc)
    if key.revoked_at is not None:
        return f"revoked at {key.revoked_at} ({key.revoked_reason}): no receipt it signed is trusted"
    if not key.has_window:
        return "no dates (v1): trusted for any receipt it signed"
    if now < _parse_time(key.valid_from):
        return f"trusted for receipts issued from {key.valid_from} (not yet)"
    if key.not_after is None:
        return f"active since {key.valid_from}"
    if now < _parse_time(key.not_after):
        return f"active since {key.valid_from}, retiring at {key.not_after}"
    return f"retired at {key.not_after}: trusted for receipts issued {key.valid_from} to {key.not_after}"


def store_show(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    keys = parse_trust_store(text)
    print(f"Trust store {path}")
    print(f"  format: {strict_loads(text)['format']}")
    print(f"  sha256: {hashlib.sha256(text.encode('utf-8')).hexdigest()}")
    for kid, key in keys.items():
        print(f"  {kid}: {key_state(key)}")
    return 0


def _store_time_arg(value: str) -> str:
    _store_time(value, "the date given")
    return value


def _trust_store_main(args: argparse.Namespace) -> int:
    try:
        if args.store_cmd == "show":
            return store_show(args.store)
        if args.store_cmd == "add":
            strict_b64(args.public_key, PUBLIC_KEY_RE, "--public-key")
            if args.valid_from is not None:
                _store_time_arg(args.valid_from)
            digest = store_add(args.store, args.id, args.public_key, args.valid_from)
        elif args.store_cmd == "retire":
            if args.at is not None:
                _store_time_arg(args.at)
            digest = store_retire(args.store, args.id, args.at)
        else:
            if args.at is not None:
                _store_time_arg(args.at)
            if not args.reason.strip():
                raise ReceiptError("--reason must say why the key is revoked")
            digest = store_revoke(args.store, args.id, args.reason, args.at)
    except (ContractError, ReceiptError, OSError, ValueError) as exc:
        print(f"error: {exc}. The trust store was not changed.", file=sys.stderr)
        return 2
    print(f"wrote {args.store} (sha256 {digest}). Publish this digest beside the store; see docs/trust-store.md.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """``python -m expectrail.receipt trust-check ...``: as ``expectrail trust-check``, with 2 for nothing checked."""
    parser = argparse.ArgumentParser(prog="expectrail.receipt")
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("trust-check", help="verify a receipt against a trust store")
    _trust_check_options(check)
    store = sub.add_parser("trust-store", help="show or edit a v2 trust store (public keys only)")
    store_sub = store.add_subparsers(dest="store_cmd", required=True)
    show = store_sub.add_parser("show", help="each key and what it is trusted for now, and the file's sha256")
    show.add_argument("store", type=Path)
    add = store_sub.add_parser("add", help="add an issuer's public key (creates a v2 store if there is none)")
    add.add_argument("store", type=Path)
    add.add_argument("--id", required=True)
    add.add_argument("--public-key", required=True, help="canonical base64 of the 32-byte Ed25519 PUBLIC key")
    add.add_argument("--valid-from", default=None, help="RFC 3339; the default is now")
    retire = store_sub.add_parser("retire", help="refuse a key's receipts issued at or after a time")
    retire.add_argument("store", type=Path)
    retire.add_argument("--id", required=True)
    retire.add_argument("--at", default=None, help="RFC 3339; the default is now")
    revoke = store_sub.add_parser("revoke", help="refuse every receipt a key signed, whatever its date")
    revoke.add_argument("store", type=Path)
    revoke.add_argument("--id", required=True)
    revoke.add_argument("--reason", required=True)
    revoke.add_argument("--at", default=None, help="RFC 3339; the default is now")
    args = parser.parse_args(argv)
    if args.cmd == "trust-check":
        return _trust_check(args, 2)
    if args.cmd == "trust-store":
        return _trust_store_main(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
