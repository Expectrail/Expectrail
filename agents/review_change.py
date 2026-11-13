"""Review a candidate fix: the same public checks on the failing base and on the candidate.

    python3 -m agents.review_change --request rr.json --candidate fix.patch --out runs/review
    python3 -m agents.review_change --request rr.json --candidate fix.patch --out runs/review \\
        --mode sample --base-observations base-obs.json --observations obs.json

The failing base is the request's seed patch alone; the candidate is seed plus the patch. Both are
judged on the request's public route by the same code (agents.verifier.public_route_checks), and
the candidate also goes through the full verifier (clean game, private routes). The review then
pairs the public checks claim by claim (expectrail.change_evidence) and writes change-evidence.json.
A requested claim that went from FAIL to PASS is then replayed on the public route twice more on each
side, and the repair counts only when it held on every run, three of three: the gate's rule (#284).

Exit 0: REPAIR DEMONSTRATED. Exit 1: REJECTED or NO REPAIR DEMONSTRATED. Exit 2: INCONCLUSIVE.
No status authorizes a merge or a release; each describes the evidence and its limits.

--mode live (the default) requires replays from the harness for both arms and the private routes;
anything less is INCONCLUSIVE. --mode sample runs on fixture observations and is labelled SAMPLE.
Mode sets what is required; it never changes what is recorded. This command never runs a fixer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from agents.patchutil import assert_editable, sha256_file
from harness.run import REPO, tree_digest
from expectrail.contracts import digest, load, validate

FORMAT = "expectrail.change-evidence/v0"
EXIT = {"REPAIR DEMONSTRATED": 0, "REJECTED": 1, "NO REPAIR DEMONSTRATED": 1, "INCONCLUSIVE": 2}
FIXTURES = REPO / "agents" / "fixtures"
PUBLIC_KINDS = ("regression", "gameplay")
# Held-out arm sources that count as the private routes having been judged (or not needed, after a
# definite fail). Anything else (the interim fixture, unavailable) cannot support a live repair.
PRIVATE_OK = ("harness", "not-run")
_SECRET = re.compile(r"\b(?:msk|sk|ghp|gho|ghs|github_pat|xox[abp])[-_A-Za-z0-9]{12,}")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize(text: str, out: Path | None = None) -> str:
    """Drop key-like strings and machine paths from text that leaves the run."""
    text = _SECRET.sub("[redacted]", str(text))
    for root, label in ((out, "<out>"), (REPO, "<repo>"), (Path.home(), "~")):
        if root is not None:
            text = text.replace(str(root), label)
    return text[:600]


class _Stages:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def run(self, stage: str):
        stages = self

        class _Stage:
            def __enter__(self):
                self.row = {"stage": stage, "status": "running", "startedAt": _now()}
                stages.items.append(self.row)
                return self.row

            def __exit__(self, exc_type, exc, _tb):
                self.row["endedAt"] = _now()
                if self.row["status"] == "running":
                    self.row["status"] = "failed" if exc_type else "completed"
                return False

        return _Stage()

    def skip(self, stage: str, reason: str) -> None:
        self.items.append({"stage": stage, "status": "skipped", "reason": reason})


def _diag(code: str, stage: str, detail: str, fix: str, out: Path | None = None) -> dict:
    return {"code": code, "stage": stage, "detail": sanitize(detail, out), "fix": fix}


def _origin(candidate: Path, origin: str | None) -> str:
    if origin:
        return origin
    try:
        candidate.resolve().relative_to(FIXTURES)
        return "fixture"
    except ValueError:
        return "developer"


def _frame(frames_dir: str | Path | None, index: int | None, dest: Path, name: str) -> dict | None:
    """Copy one replay frame into the review's assets; None when there is no such frame."""
    if frames_dir is None or index is None:
        return None
    src = Path(frames_dir) / f"f{int(index):08d}.png"
    if not src.is_file():
        return None
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"{name}.png"
    shutil.copy2(src, target)
    return {"path": f"assets/{target.name}", "frame": int(index),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def evidence_label(base_arm: dict | None, verification: dict | None, mode: str) -> str:
    """SAMPLE, FRESH LIVE or MIXED OR INCOMPLETE, from what each arm recorded (never from the mode)."""
    suite = (verification or {}).get("suite") or {}
    sources = [(base_arm or {}).get("source"),
               (suite.get("candidate") or {}).get("source"),
               (suite.get("clean") or {}).get("source")]
    held = (suite.get("heldOut") or {}).get("source")
    if base_arm is None or verification is None or None in sources:
        return "MIXED OR INCOMPLETE"
    if all(s == "fixture" for s in sources):
        return "SAMPLE"
    if all(s == "harness" for s in sources) and held in PRIVATE_OK:
        return "FRESH LIVE"
    return "MIXED OR INCOMPLETE"


def _private_summary(verification: dict | None) -> dict:
    """Counts only: no private route names, paths or frames leave the verifier's directory."""
    held = [c for c in (verification or {}).get("checks") or [] if c["kind"] == "held-out"]
    source = (((verification or {}).get("suite") or {}).get("heldOut") or {}).get("source")
    return {"source": source, "checks": len(held),
            "passed": sum(c["result"] == "pass" for c in held),
            "failed": sum(c["result"] == "fail" for c in held),
            "needsReview": sum(c["result"] == "needs-review" for c in held)}


def _reuse(verification_path: Path, candidate: Path, request: dict) -> tuple[dict | None, str | None]:
    """A verification made earlier, if it is bound to this patch and this request; else why not."""
    try:
        doc = load(verification_path, "verification")
    except Exception as exc:  # noqa: BLE001 - any unreadable document is a mismatch, reported
        return None, f"verification unreadable: {type(exc).__name__}: {exc}"
    cand = doc["candidate"]
    if cand["patchSha256"] != sha256_file(candidate):
        return None, "verification is for a different patch"
    if cand.get("requestSha256") != digest(request):
        return None, "verification is for a different request"
    return doc, None


def review(
    request: dict,
    candidate: Path,
    out: Path,
    *,
    mode: str = "live",
    origin: str | None = None,
    verification_path: Path | None = None,
    base_observations: Path | None = None,
    observations: Path | None = None,
) -> dict:
    """Run the review and write change-evidence.json in ``out``; returns the record. Never raises
    for a failure in the run itself: that is recorded and the status is INCONCLUSIVE."""
    from expectrail import change_evidence
    from agents import verifier

    record_repair = change_evidence.repair_block([], {})
    if mode not in ("live", "sample"):
        raise ValueError(f"mode must be live or sample, not {mode!r}")
    out.mkdir(parents=True, exist_ok=True)
    stages, diagnostics = _Stages(), []
    record: dict = {
        "format": FORMAT,
        "runId": f"review-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{time.time_ns() % 100000:05d}",
        "mode": mode,
        "request": {"id": request.get("id"), "sha256": digest(request)},
        "candidate": {"patchSha256": sha256_file(candidate) if candidate.is_file() else None,
                      "origin": _origin(candidate, origin)},
        "verification": None,
        "arms": {"base": None, "candidate": None},
        "rows": [],
        "private": _private_summary(None),
        "stages": stages.items,
        "diagnostics": diagnostics,
        "evidenceLabel": "MIXED OR INCOMPLETE",
        "status": "INCONCLUSIVE",
        "reasons": [],
        "repair": record_repair,
    }
    seed = request.get("base", {}).get("patch")
    rerun = ["python3", "-m", "agents.review_change", "--request", "<request.json>", "--candidate",
             "<candidate.patch>", "--mode", mode, "--out", "<new folder>"]
    if mode == "sample":
        rerun += ["--base-observations", str(base_observations), "--observations", str(observations)]
    record["rerun"] = sanitize(" ".join(rerun), out)  # no machine paths leave the run

    target = out / "change-evidence.json"
    existed = target.exists()

    def finish(status: str, reasons: list[str]) -> dict:
        record["status"], record["reasons"] = status, [sanitize(r, out) for r in reasons]
        row = {"stage": "export", "status": "running", "startedAt": _now()}
        stages.items.append(row)
        validate(record, "change-evidence")
        row.update(status="completed", endedAt=_now())
        if not existed:  # a review is never overwritten; a refused rerun only returns its record
            target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return record

    # Preflight: everything that can be checked before any game code runs.
    with stages.run("preflight") as row:
        problems: list[tuple[str, str, str]] = []
        try:
            validate(request, "repair-request")
        except Exception as exc:  # noqa: BLE001
            problems.append(("INPUT_INVALID", f"repair request invalid: {exc}", "fix the request"))
        if not candidate.is_file():
            problems.append(("INPUT_INVALID", f"candidate patch missing: {candidate}", "pass an existing patch"))
        if not seed or not (REPO / seed).is_file():
            problems.append(("INPUT_INVALID", f"the request's seed patch is missing: {seed}",
                             "the failing base needs the request's seed patch"))
        if existed:
            problems.append(("INPUT_INVALID", "the output folder already holds a review", "use a new folder"))
        if mode == "sample" and (base_observations is None or observations is None):
            problems.append(("INPUT_INVALID", "sample mode needs --base-observations and --observations",
                             "pass both, or use --mode live"))
        if mode == "live" and (base_observations or observations):
            problems.append(("INPUT_INVALID", "live mode replays both arms; observations are for sample mode",
                             "drop the observations, or use --mode sample"))
        if not problems and request["base"]["tree"] != tree_digest(REPO / "game" / "platformer"):
            problems.append(("BASE_MISMATCH", "the request's base tree is not this game",
                             "make the request against this checkout"))
        if not problems and mode == "live":
            try:
                from harness.run import find_godot
                find_godot()
            except (SystemExit, FileNotFoundError, OSError) as exc:
                problems.append(("TOOL_MISSING", f"Godot not found: {exc}", "run ./harness/get_godot.sh"))
        scope = None
        if not problems:
            scope = assert_editable(candidate.read_text(encoding="utf-8"), request["editable"])
            if scope:
                problems.append(("PATCH_SCOPE_BLOCKED", f"candidate edits paths outside the request: {scope}",
                                 "a fix may only edit the request's editable paths"))
        if problems:
            row["status"] = "failed"
            diagnostics.extend(_diag(code, "preflight", detail, fix, out) for code, detail, fix in problems)
    if problems:
        for name in ("base", "candidate", "compare", "repeat"):
            stages.skip(name, "preflight failed")
        status = "REJECTED" if scope else "INCONCLUSIVE"
        return finish(status, [d["detail"] for d in diagnostics])

    primary = {f["spec"]["id"] for f in request["failing"]}

    # The failing base: the seed alone, on the request's public route.
    base_checks, base_arm = None, None
    with stages.run("base") as row:
        try:
            base_checks, base_arm = verifier.public_route_checks(
                request, [REPO / seed], out / "base", observations_path=base_observations)
        except BaseException as exc:  # noqa: BLE001 - SystemExit from the verifier included
            if isinstance(exc, KeyboardInterrupt):
                raise
            row["status"] = "failed"
            (out / "base-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            diagnostics.append(_classify(exc, "base", out))

    # The candidate: the full verifier, or a verification already bound to this patch and request.
    verification, verification_file = None, None
    with stages.run("candidate") as row:
        try:
            if verification_path is not None:
                verification, problem = _reuse(verification_path, candidate, request)
                if problem:
                    row["status"] = "failed"
                    diagnostics.append(_diag("EVIDENCE_MISMATCH", "candidate", problem,
                                             "verify this patch for this request again", out))
                else:
                    verification_file = verification_path
                    row["reused"] = True
            else:
                verification = verifier.verify(request, candidate, out / "verify",
                                               observations_path=observations,
                                               skip_harness=observations is not None)
                verification_file = out / "verify" / "verification.json"
        except BaseException as exc:  # noqa: BLE001
            if isinstance(exc, KeyboardInterrupt):
                raise
            row["status"] = "failed"
            (out / "candidate-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            diagnostics.append(_classify(exc, "candidate", out))
            verification = None

    if verification is not None:
        record["verification"] = {"fileSha256": sha256_file(verification_file),
                                  "decision": verification["decision"]}
        record["private"] = _private_summary(verification)
    cand_identity = verifier.public_route_identity(request)
    if verification is not None and verification["evaluator"]["version"] != cand_identity["evaluator"]:
        cand_identity = dict(cand_identity, evaluator=verification["evaluator"]["version"])
    cand_frames = (Path(verification_file).parent / "replay" / "frames") if verification_file else None
    first = (base_arm or {}).get("firstFailFrame")
    if base_arm is not None:
        record["arms"]["base"] = {
            "provenance": base_arm["source"], "patchesSha256": base_arm["patchesSha256"],
            "replaySha256": base_arm["replaySha256"], "observationBackend": base_arm["identity"]["observer"],
            "frame": _frame(base_arm.get("framesDir"), first, out / "assets", "base"),
        }
    if verification is not None:
        cand_suite = (verification.get("suite") or {}).get("candidate") or {}
        record["arms"]["candidate"] = {
            "provenance": cand_suite.get("source"), "patchesSha256": [sha256_file(REPO / seed),
                                                                       verification["candidate"]["patchSha256"]],
            "replaySha256": None, "observationBackend": cand_identity["observer"],
            "frame": _frame(cand_frames, first, out / "assets", "candidate"),
        }
        replay = Path(verification_file).parent / "replay" / "replay.json"
        if replay.is_file():
            record["arms"]["candidate"]["replaySha256"] = sha256_file(replay)
    for arm_name in ("base", "candidate"):
        arm = record["arms"][arm_name]
        if arm is not None and first is not None and arm["frame"] is None and mode == "live":
            diagnostics.append(_diag("OBSERVATION_INVALID", "export", f"{arm_name} frame {first} missing",
                                     "the review shows no frame rather than an unrelated one", out))

    record["evidenceLabel"] = evidence_label(base_arm, verification, mode)
    if base_checks is None or verification is None:
        stages.skip("compare", "an arm did not complete")
        stages.skip("repeat", "an arm did not complete")
        return finish("INCONCLUSIVE", [d["detail"] for d in diagnostics] or ["an arm did not complete"])

    with stages.run("compare"):
        cand_checks = [c for c in verification["checks"] if c["kind"] in PUBLIC_KINDS]
        record["rows"] = change_evidence.pair(base_checks, cand_checks, primary=primary,
                                              base_ids=base_arm["identity"], candidate_ids=cand_identity)
        claims = change_evidence.repair_claims(record["rows"])
        runs = {(c["spec"], c["route"]): {"base": [c["before"]], "head": [c["after"]]} for c in claims}
        # Whether the status could be REPAIR DEMONSTRATED if every claim held on every run: only then are
        # the claims replayed again, so a review that cannot claim a repair costs no more than before.
        hopeful = {key: {"base": ["fail"] * change_evidence.REPAIR_RUNS, "head": ["pass"] * change_evidence.REPAIR_RUNS}
                   for key in runs}
        could, _ = change_evidence.review_status(record["rows"], verification,
                                                 change_evidence.repair_block(record["rows"], hopeful))
    # Live mode needs fresh replays and the private routes before it may claim a repair at all.
    blocked = mode == "live" and record["evidenceLabel"] != "FRESH LIVE"
    repeat_failed = False
    if could != "REPAIR DEMONSTRATED":
        stages.skip("repeat", "no repair can be claimed from the first run, so nothing is replayed again")
    elif blocked:
        stages.skip("repeat", "live mode cannot claim a repair from this evidence, so nothing is replayed again")
    else:
        # The gate's rule (expectrail.gate.record.row_counts): a claim demonstrates the repair only when
        # it fails on the base and passes on the candidate REPAIR_RUNS times of REPAIR_RUNS. The first
        # run is the one above; the public route is replayed again on each side by the same code
        # (verifier.public_route_checks; tests/test_base_arm.py holds it to verify()'s public checks).
        with stages.run("repeat") as row:
            try:
                arms = (("base", [REPO / seed], base_observations, base_arm["identity"]),
                        ("candidate", [REPO / seed, candidate], observations, cand_identity))
                for n in range(2, change_evidence.REPAIR_RUNS + 1):
                    for side, patches, obs, identity in arms:
                        checks, arm = verifier.public_route_checks(request, patches, out / f"{side}-run{n}",
                                                                   observations_path=obs)
                        same = change_evidence.mismatch(identity, arm["identity"]) == []
                        got = {(c["spec"], c["route"]): c["result"] for c in checks}
                        for key, kept in runs.items():
                            # A run judged another way (another observer, evaluator or route) is no run of
                            # this claim: it is recorded as missing, and a missing run never counts.
                            kept["base" if side == "base" else "head"].append(got.get(key) if same else None)
            except BaseException as exc:  # noqa: BLE001 - SystemExit from the verifier included
                if isinstance(exc, KeyboardInterrupt):
                    raise
                row["status"] = "failed"
                repeat_failed = True
                (out / "repeat-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
                diagnostics.append(_classify(exc, "repeat", out))
    record["repair"] = change_evidence.repair_block(record["rows"], runs)
    status, reasons = change_evidence.review_status(record["rows"], verification, record["repair"])
    reasons = list(reasons)
    if repeat_failed:
        status = "INCONCLUSIVE"
        reasons = [f"the claimed repair could not be replayed {change_evidence.REPAIR_RUNS} times on each side: "
                   + diagnostics[-1]["detail"]]
    elif could == "REPAIR DEMONSTRATED" and blocked:
        # Why nothing was replayed again is the reason, not the single run it left.
        status, reasons = "INCONCLUSIVE", []
        reasons.append(f"live mode needs fresh replays and the private routes; the evidence is "
                       f"{record['evidenceLabel'].lower()} (private routes: {record['private']['source']})")
        diagnostics.append(_diag("PRIVATE_SUITE_UNAVAILABLE"
                                 if record["private"]["source"] not in PRIVATE_OK else "OBSERVATION_INVALID",
                                 "compare", reasons[-1], "mount the private set, or review in sample mode", out))
    return finish(status, reasons)


def _classify(exc: BaseException, stage: str, out: Path) -> dict:
    from expectrail.diagnostics import classify

    doc = classify(exc, stage=stage, detail=str(exc))
    doc["detail"] = sanitize(doc.get("detail", ""), out)
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--mode", choices=("live", "sample"), default="live")
    p.add_argument("--origin", choices=("muse", "fixture", "developer"),
                   help="where the patch came from (default: fixture for agents/fixtures, else developer)")
    p.add_argument("--verification", type=Path, help="reuse this verification.json if it is bound to the patch")
    p.add_argument("--base-observations", type=Path, help="sample mode: observations of the failing base")
    p.add_argument("--observations", type=Path, help="sample mode: observations of the candidate")
    args = p.parse_args(argv)
    out = args.out.resolve()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    record = review(request, args.candidate.resolve(), out, mode=args.mode, origin=args.origin,
                    verification_path=args.verification,
                    base_observations=args.base_observations, observations=args.observations)
    reason = "; ".join(record["reasons"])[:300] or "none"
    print(f"::notice title=Review {record['status']}::{record['evidenceLabel']}; candidate from "
          f"{record['candidate']['origin']}; verifier {(record['verification'] or {}).get('decision')}; {reason}")
    return EXIT[record["status"]]


if __name__ == "__main__":
    sys.exit(main())
