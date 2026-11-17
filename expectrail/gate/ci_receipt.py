"""Produce/check the existing receipt contract for the trusted recorded-vision CI job.

    python -m expectrail.gate.ci_receipt write --help
    python -m expectrail.gate.ci_receipt check --help

The producer consumes an already judged public capture; it never replays, observes,
fixes or decides a change. The proposed workflow runs it only after trusted judgment.
The checker reuses gh/attestation.check and the existing trust-check implementation.
Exit: 0 clearance, 1 no clearance, 2 nothing checked / unusable producer input.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import stat
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

SHA40 = re.compile(r"[0-9a-f]{40}")
SHA64 = re.compile(r"[0-9a-f]{64}")
RECEIPT_CAP = 16 * 1024**2
PROFILE = "recorded-ci/v1"


def _bytes(path: Path, cap: int = RECEIPT_CAP) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
        raise ValueError(f"not a bounded regular file: {path.name!r}")
    with path.open("rb") as stream:
        data = stream.read(cap + 1)
    if len(data) > cap:
        raise ValueError(f"file exceeds its size limit: {path.name!r}")
    return data


def _sha(path: Path) -> str:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("not a regular evidence file")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            h.update(chunk)
    return h.hexdigest()


def commit_digest(commit: str) -> str:
    if not SHA40.fullmatch(commit):
        raise ValueError("a lowercase 40-digit Git commit is required")
    return hashlib.sha256(commit.encode("ascii")).hexdigest()


def policy_digest(base: str, checks: str) -> str:
    from expectrail.contracts import digest
    commit_digest(base)
    if not SHA64.fullmatch(checks):
        raise ValueError("a captured checks SHA-256 is required")
    return digest({"base": base, "checksSha256": checks, "rule": "both", "sandbox": "required",
                   "observer": PROFILE})


def _artifact(root: Path, name: str) -> Path:
    parts = PurePosixPath(name)
    if (not name or parts.is_absolute() or parts.as_posix() != name or "\\" in name
            or ":" in name or any(p in (".", "..") for p in parts.parts)):
        raise ValueError("unsafe evidence path")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("evidence root is missing or is a link")
    path = root
    for part in parts.parts:
        path /= part
        if path.is_symlink():
            raise ValueError("unsafe evidence link")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("not a regular evidence file")
    return path


def write_recorded(report: Path, capture: Path, state: Path, *, repository: str) -> Path:
    """Adapt the trusted gate result to receipt/v1. Only this CI profile has known $0 model cost.

    State is the existing ci_checks.start output, outside the candidate checkout.
    The workflow must run this after judge succeeds and keep all inputs immutable.
    The fresh signing key stays in memory; its public key alone grants no authority.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from expectrail import attestation, contracts, receipt
    from expectrail.gate import record
    from tools import ci_bundle

    if not attestation.REPO_RE.fullmatch(repository):
        raise ValueError("repository must be OWNER/NAME")
    if report.is_symlink() or not report.is_dir():
        raise ValueError("trusted report directory is missing or is a link")
    out = report / "receipt.json"
    if out.exists() or out.is_symlink():
        raise ValueError("receipt already exists; it is never overwritten")
    findings = report / "findings.json"
    original = _bytes(findings, record.MAX_RECORD_BYTES)
    doc = record.read_record(findings)
    state_doc = contracts.strict_loads(_bytes(state).decode("utf-8"))
    if (not isinstance(state_doc, dict) or state_doc.get("pr") != doc.get("pullRequest")
            or state_doc.get("intent") != record.intent_of(doc)):
        raise ValueError("trusted state and findings identity/intent differ")
    pr = state_doc["pr"]
    if not pr or doc["checksFrom"] != "base" or doc["heldOut"]["status"] != "not-used":
        raise ValueError("this producer needs a public base-policy CI result")
    base, head = pr["baseSha"], pr["headSha"]
    if doc["expectrail"]["commit"] != base:
        raise ValueError("trusted state and verifier base commit differ")
    if record.rule_of(doc) != record.BOTH:
        raise ValueError("this producer requires the recorded CI both-observer profile")
    if not doc["observers"]["visual"]["provider"].startswith("recorded: "):
        raise ValueError("the $0 producer requires a recorded-bank stamp; live-provider results are unsupported")
    if capture.stat().st_size > ci_bundle.MAX_BYTES:
        raise ValueError("capture exceeds the CI bundle limit")
    captured_sha = _sha(capture)
    versions = set()
    with tempfile.TemporaryDirectory(prefix="expectrail-receipt-") as tmp:
        saved = Path(tmp) / "capture"
        ci_bundle.unpack(capture, saved)
        manifest = contracts.strict_loads(_bytes(saved / "manifest.json", 1024**2).decode("utf-8"))
        contracts.validate(manifest, ci_bundle.SCHEMA)
        if (manifest["pullRequest"] != pr or manifest["writerRef"] != base
                or manifest["intent"] != state_doc["intent"]):
            raise ValueError("capture and trusted state identity/intent differ")
        routes = {r["sha256"]: r["name"] for r in doc["routes"]}
        if {r["route"] for r in manifest["runs"]} != set(routes):
            raise ValueError("capture and findings route sets differ")
        expected = {(g, r) for g in ci_bundle.groups(state_doc["intent"]) for r in routes}
        if len(manifest["runs"]) != len(expected) or {(r["group"], r["route"]) for r in manifest["runs"]} != expected:
            raise ValueError("capture repetition coverage differs")
        for row in manifest["runs"]:
            data = _bytes(saved / row["group"] / row["route"] / "replay.json", 1024**2)
            replay = contracts.strict_loads(data.decode("utf-8"))
            contracts.validate(replay, "replay")
            side = "base" if row["group"].startswith("base-") else "head"
            if (hashlib.sha256(data).hexdigest() != row["replay"]
                    or replay["route"]["sha256"] != row["route"]
                    or replay["route"]["name"] != routes[row["route"]]
                    or replay["game"]["tree"] != doc["game"][side + "Tree"]
                    or replay["engine"]["name"] != doc["adapter"]):
                raise ValueError("capture replay identity or digest differs from findings")
            versions.add(replay["engine"]["name"] + "/" + replay["engine"]["version"])
    if len(versions) != 1 or next(iter(versions)).endswith(("/unknown", "/")):
        raise ValueError("capture has missing or inconsistent engine versions")
    rows = [r for r in doc["checks"] if r["after"] != "not-applicable"]
    if not rows:
        raise ValueError("no required checks were recorded; no receipt is written")
    results = {contracts.digest([r["spec"], r["route"]]):
               r["after"] if r["after"] in ("pass", "fail") else "error" for r in rows}
    isolation = doc["isolation"]
    full = (doc["decision"] == "accept" and isolation["required"]
            and isolation["replays"] > 0 and isolation["sandboxed"] == isolation["replays"])
    artifacts = {"capture.zip": captured_sha}
    for path in sorted(report.rglob("*")):
        if path.is_symlink():
            raise ValueError("trusted report contains an evidence link")
        if path.is_file():
            name = "report/" + path.relative_to(report).as_posix()
            _artifact(report, path.relative_to(report).as_posix())
            artifacts[name] = _sha(path)
    if len(artifacts) > ci_bundle.MAX_FILES:
        raise ValueError("too many evidence files for a CI receipt")
    if _bytes(findings, record.MAX_RECORD_BYTES) != original or _sha(capture) != captured_sha:
        raise ValueError("trusted findings or capture changed during receipt production")
    key = Ed25519PrivateKey.generate()
    now = datetime.now(timezone.utc)
    payload = {"format": receipt.FORMAT, "issuerKeyId": "ci-ephemeral", "repository": repository,
               "baseSha256": commit_digest(base), "headSha256": commit_digest(head),
               "buildSha256": doc["game"]["headTree"],
               "policySha256": policy_digest(base, manifest["checksSha256"]),
               "routeSetSha256": contracts.digest({r["name"]: r["sha256"] for r in doc["routes"]}),
               "versions": {"verifier": doc["expectrail"]["version"] + "@" + base,
                            "adapter": next(iter(versions)),
                            "observer": PROFILE + ":" + doc["observers"]["visual"]["model"]},
               "evidence": {"grade": "full" if full else "partial",
                            "capabilities": ["engine-record", "frames", "recorded-vision"]
                            + (["replay-sandbox"] if isolation["required"] and isolation["sandboxed"] == isolation["replays"] else []),
                            "artifacts": artifacts},
               "coverage": {"required": sorted(results), "exercised": sorted(k for k,v in results.items() if v in ("pass", "fail")),
                            "results": results}, "decision": doc["decision"],
               "findings": [{"id": f["id"]} for f in doc["findings"]], "cost": {"usd": 0.0},
               "issuedAt": now.isoformat(), "expiresAt": (now + timedelta(days=1)).isoformat(),
               "algorithm": "ed25519", "publicKey": base64.b64encode(key.public_key().public_bytes_raw()).decode("ascii")}
    signed = receipt.write_receipt(payload, key)
    with out.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(signed, indent=2) + "\n")
    return out


def check(path: Path, *, repository: str, workflow: str, source_ref: str, expect_head: str,
          expect_build: str, expect_policy: str, evidence_root: Path, bundle: Path | None = None,
          runner=None) -> int:
    """Run the existing attestation and trust checks, plus every named artifact's disk digest."""
    try:
        from expectrail import attestation, receipt
        before = _bytes(path)
        doc = receipt.read_receipt(path)
        for value in (expect_head, expect_build, expect_policy):
            if not isinstance(value, str) or not SHA64.fullmatch(value):
                raise ValueError("independent head, build and policy SHA-256 expectations are required")
        print("gh attestation verify / attestation check:")
        issuer = attestation.check(path, repo=repository, signer_workflow=workflow,
                                   source_ref=source_ref, bundle=bundle, runner=runner)
        attestation.print_report(issuer)
        if path.read_bytes() != before:
            raise ValueError("receipt changed while it was checked")
        result = receipt.check_receipt(doc, {}, expect_repo=repository, expect_head=expect_head,
                                       expect_build=expect_build, expect_policy=expect_policy,
                                       attestation=issuer, receipt_sha256=hashlib.sha256(before).hexdigest())
        gaps = []
        if issuer["attested"]:
            named = doc["evidence"]["artifacts"]
            if not named:
                gaps.append("receipt names no evidence artifacts")
            for name, digest in sorted(named.items()):
                try:
                    actual = _sha(_artifact(evidence_root, name))
                    if actual != digest:
                        gaps.append(f"artifact {json.dumps(name)}: SHA-256 mismatch")
                except (OSError, ValueError) as exc:
                    reason = "missing or unreadable" if isinstance(exc, OSError) else str(exc)
                    gaps.append(f"artifact {json.dumps(name)}: {reason}")
            if path.read_bytes() != before:
                raise ValueError("receipt changed while artifacts were checked")
        if gaps:
            for gap in gaps:
                print("missing: " + gap)
            for reason in result["reasons"]:
                print("trust-check: " + reason)
            print("trust-check: no clearance; evidence artifacts do not match")
            return 1
        if issuer["attested"]:
            print(f"artifacts: MATCHED ({len(doc['evidence']['artifacts'])})")
        print("trust-check:")
        receipt._print_report(result)
        return 0 if result["clearance"] else 1
    except ImportError:
        print("nothing checked: install expectrail[trust] (cryptography and jsonschema)")
    except Exception as exc:
        # Every read/check failure stays a named refusal. No exception is clearance.
        print(f"nothing checked: {type(exc).__name__}: {exc}")
    return 2


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
        epilog="check: 0 clearance, 1 no clearance, 2 nothing checked; write: 0 written, 2 no receipt written")
    sub = p.add_subparsers(dest="command", required=True)
    w = sub.add_parser("write", help="adapt a completed trusted recorded-vision judgment to receipt/v1")
    for name in ("report", "capture", "state"):
        w.add_argument("--"+name, required=True, type=Path)
    w.add_argument("--repo", required=True)
    w.add_argument("--recorded-vision", required=True, action="store_true", help="only the current $0 recorded CI profile is supported")
    c = sub.add_parser("check", help="verify pinned issuer, every artifact and the existing trust-check conditions")
    c.add_argument("receipt", type=Path)
    c.add_argument("--repo", required=True)
    c.add_argument("--signer-workflow", required=True)
    c.add_argument("--source-ref", default="refs/heads/main")
    c.add_argument("--bundle", type=Path)
    c.add_argument("--evidence-root", type=Path, required=True)
    for name in ("head", "build", "policy"):
        c.add_argument("--expect-"+name, required=True)
    a = p.parse_args(argv)
    if a.command == "check":
        return check(a.receipt, repository=a.repo, workflow=a.signer_workflow, source_ref=a.source_ref,
                     expect_head=a.expect_head, expect_build=a.expect_build, expect_policy=a.expect_policy,
                     evidence_root=a.evidence_root, bundle=a.bundle)
    try:
        print(write_recorded(a.report, a.capture, a.state, repository=a.repo))
        return 0
    except Exception as exc:
        print(f"no receipt written: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
