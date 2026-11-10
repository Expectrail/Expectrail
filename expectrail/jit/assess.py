"""The deterministic assessor: which generated checks are valid, which catch, and how strongly.

Pure functions of replay outcomes. Nothing a model said, and nothing in the patch or the bug report,
reaches these functions: they read lists of the interpreter's five outcomes per run and nothing else.

- **Valid**: the check passed on every run of the clean reference (``REPS`` of ``REPS``: no failure,
  no gap, no error, and actually exercised), and it killed at least one near-miss variant, meaning it
  failed on every run of that variant. A check that never fails on anything near the candidate tells
  us nothing about the candidate.
- **Catch**: a valid check that failed on every run of the candidate. Mixed results are ``flaky``,
  never a catch.
- **Strong** catch: the check also fails on every run of the base build (the build the bug report
  describes), so it fails where the report says the game is wrong and still fails after the change;
  or its claim is one a person approved. **Weak**: every other catch.

No outcome here rejects anything. Generated checks are advisory (docs/jit.md, rule 1).
"""
from __future__ import annotations

REPS = 3
OUTCOMES = ("pass", "fail", "not_exercised", "insufficient_observation", "execution_error")


def combine(results: list[str]) -> str:
    """One run's outcome for a check over every probe or pair it applies to."""
    if not results:
        return "not_exercised"
    for res in ("execution_error", "fail", "insufficient_observation", "pass"):
        if res in results:
            return res
    return "not_exercised"


def all_of(runs: list[str], outcome: str, reps: int = REPS) -> bool:
    return len(runs) >= reps and all(r == outcome for r in runs[:reps])


def validity(reference: list[str], variants: dict[str, list[str]], reps: int = REPS) -> dict:
    """{valid, killed, reasons} for one check."""
    reasons = []
    bad = sorted({r for r in reference if r != "pass"})
    if bad:
        reasons.append("did not pass on the reference: " + ", ".join(bad))
    elif len(reference) < reps:
        reasons.append(f"ran {len(reference)} of {reps} times on the reference")
    killed = sorted(v for v, runs in variants.items() if all_of(runs, "fail", reps))
    if not reasons and not killed:
        reasons.append("killed no near-miss variant")
    return {"valid": not reasons, "killed": killed, "reasons": reasons}


def catch(valid: bool, candidate: list[str], reps: int = REPS) -> str:
    """catch | no-catch | flaky | not-evaluated."""
    if not valid:
        return "not-evaluated"
    if len(candidate) < reps:
        return "not-evaluated"
    if all_of(candidate, "fail", reps):
        return "catch"
    if "fail" in candidate[:reps]:
        return "flaky"
    return "no-catch"


def strength(base: list[str] | None, claim_id: str, approved_claims: frozenset[str] = frozenset(),
             reps: int = REPS) -> str:
    if claim_id in approved_claims:
        return "strong"
    if base is not None and all_of(base, "fail", reps):
        return "strong"
    return "weak"
