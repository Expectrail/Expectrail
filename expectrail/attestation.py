"""A receipt's GitHub artifact attestation: the predicate the trusted job attests, and the check of it.

In CI the trusted job is meant to attest each receipt it writes (``actions/attest`` with the receipt
file as the subject and this module's predicate). Adding that step needs ``id-token: write`` and
``attestations: write``, which only a person may add (``AGENTS.md``), so no workflow does it yet.
This module is the part that needs no permission: the predicate's writer and the reader.

    python -m expectrail.attestation predicate RECEIPT --out PREDICATE.json
    python -m expectrail.attestation check RECEIPT --repo OWNER/NAME \\
        --signer-workflow OWNER/NAME/.github/workflows/FILE.yml [--source-ref refs/heads/main] [--bundle FILE]

``check`` runs ``gh attestation verify`` with every pin it has (repository, signer workflow, source
ref, predicate type, GitHub-hosted runners only), then reads gh's JSON and checks the same pins again
itself, plus what gh does not know about: the attestation's subject is this file's SHA-256, and the
predicate's copies of the receipt's repository, head, build, policy, decision and dates are the
receipt's. An attestation is accepted only when every check holds. gh missing, gh output this
reader cannot read, or a command line it cannot read: nothing is checked (exit 2).

What a verified attestation establishes is who wrote the receipt file: the named workflow, on the
named ref, in the named repository. It does not establish clearance. Whether the receipt clears a
change is ``trust-check``'s question, and this command never says it does.

Exit codes: 0 attested, 1 not attested, 2 nothing checked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import jsonschema

from expectrail import resources
from expectrail.contracts import ContractError, strict_loads

FORMAT = "expectrail.receipt-attestation/v1"
PREDICATE_TYPE = "https://expectrail.tech/attestation/receipt/v1"
SCHEMA = json.loads((resources.ROOT / "contracts" / "receipt-attestation.v1.schema.json").read_text(encoding="utf-8"))
# The receipt fields the predicate copies. A copy that differs refuses the attestation.
COPIED = ("repository", "headSha256", "buildSha256", "policySha256", "decision", "issuedAt", "expiresAt")
DEFAULT_REF = "refs/heads/main"
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", re.ASCII)
WORKFLOW_RE = re.compile(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml", re.ASCII)
REF_RE = re.compile(r"refs/(?:heads|tags)/[A-Za-z0-9_./-]+", re.ASCII)
OIDC_ISSUER = "https://token.actions.githubusercontent.com"

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class CannotCheck(Exception):
    """Nothing was checked: gh is missing, or its output, the receipt or the command line cannot be read."""


def _read_receipt(path: Path) -> tuple[bytes, dict]:
    from expectrail import receipt  # needs the trust extra; imported here so the error names it

    data = path.read_bytes()
    try:
        doc = strict_loads(data.decode("utf-8"))
        receipt._validate_receipt(doc)
    except (ContractError, receipt.ReceiptError, UnicodeDecodeError, ValueError) as exc:
        raise CannotCheck(f"the receipt cannot be read: {exc}") from exc
    return data, doc


def predicate_for(data: bytes, doc: dict) -> dict:
    """The predicate for a receipt file: its exact bytes' digest and copies of the fields a reader compares."""
    out = {"format": FORMAT, "receiptSha256": hashlib.sha256(data).hexdigest()}
    out.update({k: doc[k] for k in COPIED})
    jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker()).validate(out)
    return out


def write_predicate(receipt_path: Path, out: Path | None = None) -> dict:
    data, doc = _read_receipt(receipt_path)
    predicate = predicate_for(data, doc)
    if out is not None:
        out.write_text(json.dumps(predicate, indent=2) + "\n", encoding="utf-8")
    return predicate


def gh_command(receipt_path: Path, *, repo: str, signer_workflow: str, source_ref: str,
               bundle: Path | None = None) -> list[str]:
    """``gh attestation verify`` with every pin this reader checks again afterwards."""
    cmd = ["gh", "attestation", "verify", str(receipt_path), "--repo", repo, "--signer-workflow", signer_workflow,
           "--source-ref", source_ref, "--predicate-type", PREDICATE_TYPE, "--cert-oidc-issuer", OIDC_ISSUER,
           "--deny-self-hosted-runners", "--format", "json"]
    if bundle is not None:
        cmd += ["--bundle", str(bundle)]
    return cmd


def _default_runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def run_gh(cmd: list[str], runner: Runner | None = None) -> tuple[int, str, str]:
    try:
        done = (runner or _default_runner)(cmd)
    except FileNotFoundError as exc:
        raise CannotCheck("gh is not installed, so no attestation could be verified (https://cli.github.com)") from exc
    except subprocess.TimeoutExpired as exc:
        raise CannotCheck("gh attestation verify did not finish in 120 seconds") from exc
    return done.returncode, done.stdout or "", done.stderr or ""


def _same_repo(a: str, b: str) -> bool:
    # GitHub owner and repository names are case-insensitive; nothing else here is.
    return a.lower() == b.lower()


def _field(obj: object, *path: str) -> object:
    for name in path:
        if not isinstance(obj, dict) or name not in obj:
            raise KeyError("/".join(path))
        obj = obj[name]
    return obj


def _result_gaps(result: object, digest: str, doc: dict, *, repo: str, signer_workflow: str,
                 source_ref: str) -> list[str]:
    """Why one of gh's results is not an attestation of this receipt by this workflow. Empty: it is."""
    try:
        statement = _field(result, "verificationResult", "statement")
        cert = _field(result, "verificationResult", "signature", "certificate")
        predicate_type = _field(statement, "predicateType")
        subjects = _field(statement, "subject")
        predicate = _field(statement, "predicate")
        source_uri = _field(cert, "sourceRepositoryURI")
        signer_uri = _field(cert, "buildSignerURI")
        cert_ref = _field(cert, "sourceRepositoryRef")
        runner_env = _field(cert, "runnerEnvironment")
        issuer = _field(cert, "issuer")
    except KeyError as exc:
        return [f"gh's result has no {exc.args[0]}, so it cannot be read"]
    gaps = []
    if predicate_type != PREDICATE_TYPE:
        gaps.append(f"predicate type is {predicate_type!r}, not {PREDICATE_TYPE}")
    if not isinstance(subjects, list) or not any(
            isinstance(s, dict) and isinstance(s.get("digest"), dict) and s["digest"].get("sha256") == digest
            for s in subjects):
        gaps.append(f"no subject has this receipt's digest (sha256:{digest})")
    validator = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(predicate), key=lambda e: list(e.path)) if isinstance(predicate, dict) else []
    if not isinstance(predicate, dict) or errors:
        gaps.append(f"the predicate is not {FORMAT}" + (f": {errors[0].message}" if errors else ""))
    else:
        if predicate["receiptSha256"] != digest:
            gaps.append("the predicate names another receipt file")
        for k in COPIED:
            if predicate[k] != doc[k]:
                gaps.append(f"the predicate's {k} is not the receipt's")
    if not isinstance(source_uri, str) or not _same_repo(source_uri, f"https://github.com/{repo}"):
        gaps.append(f"signed for repository {source_uri!r}, not https://github.com/{repo}")
    expected_signer = f"https://github.com/{signer_workflow}@{source_ref}"
    if not isinstance(signer_uri, str) or "@" not in signer_uri:
        gaps.append(f"signer {signer_uri!r} cannot be read")
    else:
        where, _, ref = signer_uri.rpartition("@")
        want_where = f"https://github.com/{signer_workflow}"
        owner_repo = WORKFLOW_RE.fullmatch(signer_workflow).group(1)
        prefix = f"https://github.com/{owner_repo}/"
        if not (_same_repo(where[:len(prefix)], prefix) and where[len(prefix):] == want_where[len(prefix):]
                and ref == source_ref):
            gaps.append(f"signed by {signer_uri}, not {expected_signer}")
    if cert_ref != source_ref:
        gaps.append(f"source ref is {cert_ref!r}, not {source_ref}")
    if runner_env != "github-hosted":
        gaps.append(f"run on {runner_env!r} runners, not GitHub's")
    if issuer != OIDC_ISSUER:
        gaps.append(f"certificate issuer is {issuer!r}, not {OIDC_ISSUER}")
    return gaps


def check_attestation(data: bytes, doc: dict, gh_exit: int, gh_stdout: str, gh_stderr: str, *, repo: str,
                      signer_workflow: str, source_ref: str = DEFAULT_REF) -> dict[str, Any]:
    """Decide from gh's exit and JSON whether this receipt file is attested by ``signer_workflow``.

    gh's own verdict is required (a non-zero exit is "not attested") and is not enough: every pin is
    checked again on gh's output. Output that cannot be read raises ``CannotCheck``.
    """
    digest = hashlib.sha256(data).hexdigest()
    report: dict[str, Any] = {"attested": False, "receiptSha256": digest, "repository": repo,
                              "signerWorkflow": signer_workflow, "sourceRef": source_ref,
                              "establishes": [], "does_not_establish": ["clearance (that is trust-check's)"],
                              "reasons": []}
    if not _same_repo(doc["repository"], repo):
        report["reasons"].append(f"the receipt is about {doc['repository']}, not {repo}")
    if gh_exit != 0:
        last = next((line for line in reversed(gh_stderr.strip().splitlines()) if line.strip()), "no reason given")
        report["reasons"].append(f"gh attestation verify refused it (exit {gh_exit}): {last.strip()}")
        report["does_not_establish"].insert(0, "who wrote the receipt")
        return report
    try:
        results = json.loads(gh_stdout)
    except ValueError as exc:
        raise CannotCheck("gh said it verified the attestation, but its output is not JSON") from exc
    if not isinstance(results, list) or not results:
        raise CannotCheck("gh said it verified the attestation, but its output lists no result")
    all_gaps = []
    for i, result in enumerate(results, 1):
        gaps = _result_gaps(result, digest, doc, repo=repo, signer_workflow=signer_workflow, source_ref=source_ref)
        if not gaps:
            break
        all_gaps += [f"attestation {i}: {g}" for g in gaps]
    else:
        report["reasons"] += all_gaps
        report["does_not_establish"].insert(0, "who wrote the receipt")
        return report
    if report["reasons"]:  # the receipt names another repository: attested, but not about this one
        report["does_not_establish"].insert(0, "who wrote the receipt")
        return report
    report["attested"] = True
    report["establishes"].append(f"this receipt file (sha256:{digest}) was attested by {signer_workflow} "
                                 f"at {source_ref}, on GitHub's runners")
    return report


def check(receipt_path: Path, *, repo: str, signer_workflow: str, source_ref: str = DEFAULT_REF,
          bundle: Path | None = None, runner: Runner | None = None) -> dict[str, Any]:
    if not REPO_RE.fullmatch(repo):
        raise CannotCheck(f"--repo must be OWNER/NAME, not {repo!r}")
    match = WORKFLOW_RE.fullmatch(signer_workflow)
    if not match:
        raise CannotCheck("--signer-workflow must be OWNER/NAME/.github/workflows/FILE.yml")
    if not _same_repo(match.group(1), repo):
        raise CannotCheck("--signer-workflow must be a workflow of --repo (a reusable workflow elsewhere is not "
                          "supported)")
    if not REF_RE.fullmatch(source_ref):
        raise CannotCheck(f"--source-ref must be refs/heads/NAME or refs/tags/NAME, not {source_ref!r}")
    data, doc = _read_receipt(receipt_path)
    code, out, err = run_gh(gh_command(receipt_path, repo=repo, signer_workflow=signer_workflow,
                                       source_ref=source_ref, bundle=bundle), runner)
    # gh read the file itself: make sure it is still the file whose digest is compared.
    if receipt_path.read_bytes() != data:
        raise CannotCheck("the receipt file changed while it was being checked")
    return check_attestation(data, doc, code, out, err, repo=repo, signer_workflow=signer_workflow,
                             source_ref=source_ref)


def print_report(report: dict) -> None:
    if report["attested"]:
        print(f"attestation: VERIFIED (by {report['signerWorkflow']} at {report['sourceRef']})")
    else:
        print("attestation: NOT VERIFIED")
    print(f"receipt file: sha256:{report['receiptSha256']}")
    for item in report["establishes"]:
        print(f"establishes: {item}")
    for item in report["does_not_establish"]:
        print(f"does not establish: {item}")
    for reason in report["reasons"]:
        print(f"reason: {reason}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m expectrail.attestation",
                                     description="Write or check a receipt's GitHub artifact attestation. "
                                     "check exits 0 attested, 1 not attested, 2 nothing checked.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pred = sub.add_parser("predicate", help="write the predicate the trusted job attests for a receipt")
    pred.add_argument("receipt", type=Path)
    pred.add_argument("--out", type=Path, required=True)
    chk = sub.add_parser("check", help="verify a receipt file's attestation with gh, then check every pin again")
    chk.add_argument("receipt", type=Path)
    chk.add_argument("--repo", required=True, help="OWNER/NAME the receipt and its signer must belong to")
    chk.add_argument("--signer-workflow", required=True, help="OWNER/NAME/.github/workflows/FILE.yml")
    chk.add_argument("--source-ref", default=DEFAULT_REF, help=f"the ref the signer ran on (default {DEFAULT_REF})")
    chk.add_argument("--bundle", type=Path, default=None, help="an attestation bundle on disk (no GitHub lookup)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    try:
        if args.cmd == "predicate":
            write_predicate(args.receipt, args.out)
            print(f"wrote {args.out} (predicate type {PREDICATE_TYPE})")
            return 0
        report = check(args.receipt, repo=args.repo, signer_workflow=args.signer_workflow,
                       source_ref=args.source_ref, bundle=args.bundle)
    except (CannotCheck, OSError, jsonschema.ValidationError) as exc:
        message = exc.message if isinstance(exc, jsonschema.ValidationError) else exc
        print(f"error: {message}. Nothing was checked.", file=sys.stderr)
        return 2
    print_report(report)
    return 0 if report["attested"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
