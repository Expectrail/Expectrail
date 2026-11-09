"""Report first, evidence on rejection: what the fixer is told on each attempt.

The decision and its evidence are in docs/report-first.md. In short: Muse Code fixes these bugs as
well from a plain report as from Expectrail's evidence (45 of 46 live cases on the first attempt),
and the verifier, not the briefing, is what stops a fix that only looks right. So:

- **Attempt 1, the report:** the failing check's one sentence in plain English, screenshots of the
  failing run spaced from its first frame to its last, the route and the run's log. No spec, no
  verdict, no evidence.
- **After an attempt fails, the evidence:** the repair request (the approved spec, the evaluator's
  verdict on the failing run and its first failing frame) and, after a rejection, the verifier's
  reasons limited to the public checks. A held-out route, a guard, or the reason one failed never
  reaches the fixer, so it cannot be fixed to the test. An attempt fails when the verifier rejects
  it or when it produces no fix (it timed out or changed nothing): on October 31, report-only
  attempts on both sinking bugs timed out three times in a row while the evidence fixed each on
  the first attempt (Fix matrix run 41223754703).
- **Every candidate is verified,** whatever the fixer was told. The fixer never decides it is done.

``EXPECTRAIL_BRIEFING=evidence`` restores the previous behaviour (the evidence from attempt 1).

The engine comes from ``adapter`` (harness/adapters.py, default ``godot``): how the prompt names the
project, the physics rate the route counts in, and the name of the run's log.
"""
from __future__ import annotations

import os
from pathlib import Path

from agents.fixer import build_muse_prompt
from harness import adapters
from harness.adapters import Adapter

POLICY = "report-first-v1"
ENV = "EXPECTRAIL_BRIEFING"
MODES = ("report-first", "evidence")
BRIEFING_DIR = "bug-report"
SHOTS = 6
# Check kinds whose names and routes the fixer may see. Held-out results are kept from it.
PUBLIC_KINDS = frozenset({"regression", "gameplay", "clean"})


def mode() -> str:
    raw = (os.environ.get(ENV) or "report-first").strip().lower()
    if raw not in MODES:
        raise SystemExit(f"{ENV}={raw!r}: want one of {', '.join(MODES)}")
    return raw


def spaced(frames: list[Path], n: int = SHOTS) -> list[Path]:
    """``n`` frames evenly spaced from the first to the last, by position, never by a verdict."""
    if len(frames) <= n:
        return list(frames)
    return [frames[round(i * (len(frames) - 1) / (n - 1))] for i in range(n)]


def report_files(run_dir: Path, route_path: Path, adapter: str | Adapter = "godot") -> dict[str, Path]:
    """The files the report gives the fixer: screenshots of the failing run, its route and log."""
    log = adapters.resolve(adapter).log_name
    files: dict[str, Path] = {}
    for i, frame in enumerate(spaced(sorted((run_dir / "frames").glob("*.png")))):
        files[f"{BRIEFING_DIR}/screenshots/{i + 1:02d}-{frame.stem}.png"] = frame
    files[f"{BRIEFING_DIR}/route.json"] = route_path
    if log and (run_dir / log).is_file():
        files[f"{BRIEFING_DIR}/{log}"] = run_dir / log
    return files


def _rules(request: dict, attempt: int) -> str:
    return f"""## Rules
- Only edit files matching these globs (relative to the workspace root): {", ".join(request["editable"])}
- Do not edit anything under {BRIEFING_DIR}/, and do not create files outside those globs.
- Fix the problem without removing anything the game is meant to do. Produce the smallest correct
  fix. When done, leave the game files edited; do not commit.

Attempt {attempt} of {request["budget"]["attempts"]}."""


def report_prompt(request: dict, files: dict[str, Path], attempt: int, *, empty_before: bool = False,
                  adapter: str | Adapter = "godot") -> str:
    adapter = adapters.resolve(adapter)
    sentence = request["failing"][0]["spec"]["instruction"]
    shots = sorted(f for f in files if "/screenshots/" in f)
    again = ("\n\nYour previous attempt changed no file you may edit. Look again." if empty_before else "")
    ticks = (f" (inputs on exact physics ticks, {adapter.ticks_per_second} a second)"
             if adapter.ticks_per_second else "")
    log = f" The game's log from that run is {BRIEFING_DIR}/{adapter.log_name}." if adapter.log_name else ""
    return f"""You are fixing a bug in {adapter.prompt_subject}.

## Bug report
On the route in {BRIEFING_DIR}/route.json{ticks}, this no
longer holds: "{sentence}"

Screenshots of the game on that route, in order from its first frame to its last: {", ".join(shots)}.
Open and look at each one.{log}{again}

{_rules(request, attempt)}
"""


def evidence_prompt(request: dict, files: dict[str, Path], attempt: int, adapter: str | Adapter = "godot") -> str:
    shots = sorted(f for f in files if "/screenshots/" in f)
    base = build_muse_prompt(request, rr_relpath="repair-request.json", attempt=attempt, adapter=adapter)
    if not shots:
        return base
    return (base + f"\nScreenshots of the failing run (open and look at each one): {', '.join(shots)}; "
            f"route and log in {BRIEFING_DIR}/. Do not edit anything under {BRIEFING_DIR}/.\n")


def public_feedback(verification: dict, attempt: int) -> dict:
    """What the fixer learns from a rejection: the decision and the public checks that did not pass.

    Never a held-out check, its route or its reason. When only held-out checks failed, the fixer
    learns that the attempt was rejected and nothing else."""
    reasons = [f"{c['kind']} check {c['spec']} {'failed' if c['result'] == 'fail' else 'needs review'} on {c['route']}"
               for c in verification.get("checks") or []
               if c.get("result") != "pass" and c.get("kind") in PUBLIC_KINDS]
    return {"attempt": attempt, "decision": verification.get("decision"),
            "reasons": reasons or ["the attempt did not pass Expectrail's checks"]}


def briefing(request: dict, files: dict[str, Path] | None, attempt: int, rejected_before: bool,
             *, empty_before: bool = False, adapter: str | Adapter = "godot") -> tuple[dict | None, str]:
    """(briefing for run_fixer, stage). Stage ``report`` until an attempt has failed (rejected, or no
    fix at all), then ``evidence``. ``None`` means the fixer's own evidence prompt (no screenshots)."""
    if mode() == "evidence" or rejected_before or empty_before or not files:
        if not files:
            return None, "evidence"
        return {"prompt": evidence_prompt(request, files, attempt, adapter), "policy": f"{POLICY}-evidence",
                "files": files, "withRequest": True}, "evidence"
    return {"prompt": report_prompt(request, files, attempt, empty_before=empty_before, adapter=adapter),
            "policy": f"{POLICY}-report", "files": files, "withRequest": False}, "report"
