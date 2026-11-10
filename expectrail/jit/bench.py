"""The known-bugs bench: the live generator on bugs we already have, scored against a bar set beforehand.

    python -m expectrail.jit.cli bench-score --records runs/bench --out runs/bench-score

Rehearsals replay a committed stand-in proposal, so they prove the plumbing and say nothing about the
checks a real model writes. This bench runs the whole live pipeline (measure, propose, replay, revise,
replay) on each reported bug with two candidates: a wrong fix (a comment claiming the fix, nothing
else) and the correct fix (the exact undo). A generated check is report-only everywhere else; here
its catches are counted, because that is what the bench measures.

- A wrong fix is **caught** when a generated check fails 3 of 3 on it and on the bug build (strong).
- A correct fix is **falsely caught** by any catch, strong or weak.
- A case with no complete record is **no result**, never a pass.

The bar lives in bench/jit/known/preregistration.json, signed off before the bench runs; the workflow
refuses an unsigned registration or one whose pinned files have changed. The air-jump bug is marked
``tunedOn``: the measurements and the left-walk probes were designed while looking at it, so the bar
also asks for catches on the bugs nobody tuned on.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from expectrail.contracts import load_strict

REPO = Path(__file__).resolve().parents[2]
CASES = REPO / "bench" / "jit" / "known" / "cases.json"
PREREG = REPO / "bench" / "jit" / "known" / "preregistration.json"
PINNED = ["expectrail/jit/*.py", "expectrail/discovery/probes.py", "expectrail/discovery/route_compiler.py",
          "expectrail/discovery/planner.py", "expectrail/trace/*.py", "harness/*.py", "harness/*.sh",
          ".github/workflows/jit.yml", ".github/workflows/jit-bench.yml", "contracts/jit-run.v1.schema.json",
          "contracts/trace-spec.v1.schema.json", "discovery/platformer.profile.json",
          "bench/jit/known/**/*.patch", "bench/jit/known/**/*.txt", "bench/jit/known/cases.json",
          "bugs/reported/*.patch"]


def pins(root: Path = REPO) -> dict[str, str]:
    """sha256 of every file that decides a bench result, plus the clean game's tree as one digest."""
    out: dict[str, str] = {}
    for pattern in PINNED:
        for p in sorted(root.glob(pattern)):
            if p.is_file() and "__pycache__" not in p.parts:
                out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    game = root / "game" / "platformer"
    h = hashlib.sha256()
    for p in sorted(game.rglob("*")):
        if p.is_file() and ".godot" not in p.relative_to(game).parts:
            h.update(p.relative_to(game).as_posix().encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    out["game/platformer/**"] = h.hexdigest()
    return out


def check_registration(prereg: dict, root: Path = REPO) -> list[str]:
    """Why the bench may not run: [] when the registration is signed and every pin still holds."""
    problems = []
    if prereg.get("status") != "registered" or not prereg.get("signedOffBy"):
        problems.append("the registration is not signed off (status must be 'registered', with signedOffBy)")
    now = pins(root)
    pinned = prereg.get("pins") or {}
    if not pinned:
        problems.append("the registration pins no files")
    for path in sorted(set(pinned) | set(now)):
        if pinned.get(path) != now.get(path):
            problems.append(f"pin moved: {path}")
    return problems


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def score(cases: list[dict], records_dir: Path, bar: dict, root: Path = REPO) -> dict:
    """One row per case from ``records_dir/<case>/jit-run.json``, the totals, and the bar's verdict."""
    rows = []
    for c in cases:
        row = {k: c[k] for k in ("case", "bug", "label", "tunedOn")}
        path = Path(records_dir) / c["case"] / "jit-run.json"
        record, why = None, None
        try:
            record = load_strict(path, "jit-run")
        except (OSError, ValueError) as exc:
            why = f"no readable record ({type(exc).__name__})"
        if record is not None:
            if record["inputs"]["patchSha256"] != _sha(root / c["candidate"]):
                why, record = "the record is for another candidate", None
            elif record["inputs"]["basePatchSha256"] != [_sha(root / c["base"])]:
                why, record = "the record is for another bug", None
            elif record["status"] != "complete":
                why = f"{record['status']}: {record['reason']}"
        if record is None or record["status"] != "complete":
            row.update(outcome="no-result", why=why, proposed=0, valid=0, strong=0, weak=0, spendUsd=None)
            rows.append(row)
            continue
        strong, weak = record["counts"]["strong"], record["counts"]["weak"]
        if c["label"] == "wrong":
            outcome = "caught" if strong else ("weak-only" if weak else "missed")
        else:
            outcome = "false-catch" if strong or weak else "clean"
        row.update(outcome=outcome, why=None, proposed=record["counts"]["proposed"], valid=record["counts"]["valid"],
                   strong=strong, weak=weak, spendUsd=record["spend"]["usd"])
        rows.append(row)
    wrong = [r for r in rows if r["label"] == "wrong"]
    correct = [r for r in rows if r["label"] == "correct"]
    totals = {
        "cases": len(rows),
        "noResult": sum(r["outcome"] == "no-result" for r in rows),
        "wrongCaught": sum(r["outcome"] == "caught" for r in wrong), "wrong": len(wrong),
        "wrongCaughtUntuned": sum(r["outcome"] == "caught" for r in wrong if not r["tunedOn"]),
        "wrongUntuned": sum(not r["tunedOn"] for r in wrong),
        "correctFalseCatches": sum(r["outcome"] == "false-catch" for r in correct), "correct": len(correct),
        "casesWithAValidCheck": sum(r["valid"] > 0 for r in rows),
        "spendUsd": round(sum(r["spendUsd"] or 0 for r in rows), 4),
        "maxSpendUsd": max((r["spendUsd"] or 0 for r in rows), default=0),
    }
    reasons = []
    if totals["noResult"] > bar["maxNoResult"]:
        reasons.append(f"{totals['noResult']} cases with no result (at most {bar['maxNoResult']})")
    if totals["wrongCaught"] < bar["minWrongCaught"]:
        reasons.append(f"{totals['wrongCaught']} of {totals['wrong']} wrong fixes caught (at least {bar['minWrongCaught']})")
    if totals["wrongCaughtUntuned"] < bar["minWrongCaughtUntuned"]:
        reasons.append(f"{totals['wrongCaughtUntuned']} of {totals['wrongUntuned']} wrong fixes caught on bugs nobody "
                       f"tuned on (at least {bar['minWrongCaughtUntuned']})")
    if totals["correctFalseCatches"] > bar["maxCorrectFalseCatches"]:
        reasons.append(f"{totals['correctFalseCatches']} correct fixes caught (at most {bar['maxCorrectFalseCatches']})")
    if totals["maxSpendUsd"] > bar["maxSpendUsdPerCase"] + 1e-9:
        reasons.append(f"a case spent ${totals['maxSpendUsd']:.4f} (at most ${bar['maxSpendUsdPerCase']:.2f})")
    return {"format": "expectrail.jit-bench/v0", "rows": rows, "totals": totals,
            "verdict": "meets-bar" if not reasons else "below-bar", "reasons": reasons, "bar": bar}


def render(doc: dict) -> str:
    t = doc["totals"]
    lines = [f"# Known-bugs bench: {doc['verdict']}", "",
             f"- Wrong fixes caught (strong): {t['wrongCaught']} of {t['wrong']}; on bugs nobody tuned on: "
             f"{t['wrongCaughtUntuned']} of {t['wrongUntuned']}",
             f"- Correct fixes caught (false catches): {t['correctFalseCatches']} of {t['correct']}",
             f"- Cases with at least one valid check: {t['casesWithAValidCheck']} of {t['cases']}; no result: {t['noResult']}",
             f"- Spend: ${t['spendUsd']:.4f} in all, at most ${t['maxSpendUsd']:.4f} for one case", ""]
    lines += [f"- Below the bar: {r}" for r in doc["reasons"]] + ([""] if doc["reasons"] else [])
    lines += ["| Case | Fix | Tuned on | Proposed | Valid | Strong | Weak | Outcome |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in doc["rows"]:
        lines.append(f"| {r['case']} | {r['label']} | {'yes' if r['tunedOn'] else 'no'} | {r['proposed']} | {r['valid']} | "
                     f"{r['strong']} | {r['weak']} | {r['outcome']}{' (' + r['why'] + ')' if r['why'] else ''} |")
    return "\n".join(lines) + "\n"


def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["cases"]
