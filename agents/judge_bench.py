"""Judge benchmark: who accepts a fix that only looks right?

The fix matrix showed Muse Code fixes most bugs about as well from screenshots as with Expectrail's
evidence (the sinking bugs are the exception: docs/report-first.md). What Expectrail is for first
is the other half: telling a real fix from one that only looks right. This puts candidate fixes with a known answer in front of three judges and
counts their mistakes:

  - Expectrail's verifier with SAM on (the baseline's setting);
  - the same verifier with SAM off (position log and gameplay only);
  - Muse Code judging from screenshots alone (agents.muse_judge): five frames of the bugged run
    and five of the candidate's, on the same route, and a one-line bug report in plain English;
  - with ``--glimmer``, the verifier judged by Muse Glimmer checked against the engine, exactly as the
    judge ladder's fallback judges a candidate when SAM does not answer (agents.judge_ladder). A
    Glimmer outage leaves that judge undecided; it is never counted as a rejection.

Good candidates undo a seeded bug exactly (the bugged tree diffed back to the clean game), so the
game they produce is the clean game. Bad candidates are fixtures that stop the reported symptom
while breaking something a player would see, or that change nothing. Two of the bad ones are
outside what any approved spec checks (a floating robot, deleted scenery), so they measure
Expectrail's blind spots too, not only its strengths.

    python3 -m agents.judge_bench --list
    python3 -m agents.judge_bench --case bad/fall-through-hide-player --out runs/judge --live
    python3 -m agents.judge_bench --case bad/fall-through-sink-player --out runs/judge --live --glimmer
    python3 -m agents.judge_bench --summarize runs/judge

Offline (no ``--live``) the screenshot judge is skipped and only the verifiers run.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

from agents.matrix import (
    EDITABLE,
    SCREENSHOT_FRAMES,
    SMOKE_ROUTE,
    case_spec,
    dev_variants,
)
from agents.muse_judge import DECISION_RE, run_muse_judge
from agents.orchestrator import build_repair_request
from agents.sam_observations import sam_images_since, sam_usage
from agents.verifier import verify
from harness.run import REPO, apply_patches
from harness.run import run as harness_run
from expectrail.contracts import digest, load
from expectrail.evaluator import EVALUATOR

FORMAT = "expectrail.judge-bench/v0"
FIXTURES = REPO / "agents" / "fixtures"
GAME = REPO / "game" / "platformer"
JUDGES = ("expectrailSam", "expectrailNoSam", "expectrailGlimmer", "museScreenshots")
# What a player would report, per family: the only description the screenshot judge gets.
REPORTS = {
    "physics-fall-through": "The player falls through the ground.",
    "sinking": "The player sinks into the ground instead of standing on it.",
    "missing-texture": "The coins are invisible.",
    "layering": "The player disappears behind the scenery.",
}
# Bad candidates: (bug, fixture, why it is wrong). Each stops the reported symptom, or claims to.
BAD = {
    "bad/fall-through-hide-player": ("dev/physics-fall-through/v1", "fix-but-hide-player",
                                     "stops the fall but draws the robot behind the level art"),
    "bad/fall-through-sink-player": ("dev/physics-fall-through/v1", "fix-but-sink-player",
                                     "stops the fall but draws the robot inside the ground"),
    "bad/fall-through-lower-floor": ("dev/physics-fall-through/v1", "fix-and-lower-the-floor",
                                     "stops the fall by moving the floor's collision below its art"),
    "bad/fall-through-freeze": ("dev/physics-fall-through/v1", "freeze-player",
                                "stops the fall by making the robot unable to move or jump"),
    "bad/fall-through-comment-only": ("dev/physics-fall-through/v1", "fix-comment-only",
                                      "changes nothing but a comment: the robot still falls"),
    "bad/sinking-overcorrected": ("dev/sinking/v1", "fix-sinking-overcorrected",
                                  "the robot no longer sinks but floats above the ground"),
    "bad/layering-hide-trees": ("dev/layering/v1", "fix-layering-hide-trees",
                                "the robot shows because every tree was deleted; no spec checks the trees"),
}


def cases() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for key in dev_variants():
        out["good/" + key.removeprefix("dev/")] = {"bug": key, "fixture": None, "label": "good",
                                                   "why": "undoes the seeded bug exactly"}
    for key, (bug, fixture, why) in BAD.items():
        out[key] = {"bug": bug, "fixture": fixture, "label": "bad", "why": why}
    return out


def undo_patch(bug: Path, out: Path) -> Path:
    """The candidate that undoes a seeded bug: the bugged files diffed back to the clean game."""
    with tempfile.TemporaryDirectory() as tmp:
        bugged = Path(tmp) / "bugged"
        shutil.copytree(GAME, bugged, ignore=shutil.ignore_patterns(".godot"))
        apply_patches(bugged, [bug])
        touched = [line[6:].strip() for line in bug.read_text(encoding="utf-8").splitlines()
                   if line.startswith("+++ b/")]
        chunks = []
        for rel in touched:
            a = (bugged / rel).read_text(encoding="utf-8").splitlines(keepends=True)
            b = (GAME / rel).read_text(encoding="utf-8").splitlines(keepends=True)
            chunks.append("".join(difflib.unified_diff(a, b, fromfile=f"a/{rel}", tofile=f"b/{rel}")))
    out.write_text("".join(chunks), encoding="utf-8")
    return out


@contextmanager
def provider(name: str):
    """Run the verifier with SAM on ("sam") or off ("trace") for one block."""
    old = os.environ.get("EXPECTRAIL_OBS_PROVIDER")
    os.environ["EXPECTRAIL_OBS_PROVIDER"] = name
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("EXPECTRAIL_OBS_PROVIDER", None)
        else:
            os.environ["EXPECTRAIL_OBS_PROVIDER"] = old


def _frames(frames_dir: Path) -> list[Path]:
    frames = sorted(frames_dir.glob("*.png"))
    return [frames[n] for n in SCREENSHOT_FRAMES if n < len(frames)]


def _correct(label: str, decision: str | None) -> bool | None:
    if decision not in ("accept", "reject", "needs-review"):
        return None
    return decision == "accept" if label == "good" else decision != "accept"


def muse_reason(judge: dict, limit: int = 400) -> str:
    """What Muse wrote just before its last DECISION line (its reasoning), else the judge's own detail."""
    try:
        text = Path(judge.get("museLog") or "").read_text(encoding="utf-8")
    except (OSError, TypeError):
        return judge.get("detail") or ""
    matches = list(DECISION_RE.finditer(text))
    if not matches:
        return judge.get("detail") or ""
    said = " ".join(text[:matches[-1].start()].split())
    return ("..." + said[-limit:]) if len(said) > limit else said


def _glimmer_verify(request: dict, candidate: Path, out: Path) -> tuple[str | None, list[str]]:
    """The judge ladder's fallback on its own: the verifier with Glimmer checked against the engine.

    Returns (decision, reasons); the decision is None when Glimmer did not answer, so an outage is
    undecided rather than a rejection."""
    from agents.judge_ladder import FALLBACK, backend, glimmer_problem, judge_unavailable

    problem = glimmer_problem()
    if problem is not None:
        return None, [f"Glimmer unavailable: {problem}"]
    with provider("sam"), backend(FALLBACK):
        v = verify(request, candidate, out)
    if judge_unavailable(v, out):
        return None, ["Glimmer did not answer"]
    return v["decision"], list(dict.fromkeys(r.split(" on ")[0] for r in (v.get("reasons") or [])))[:6]


def run_case(key: str, out: Path, *, live: bool, sam: bool = True, glimmer: bool = False) -> dict:
    """One candidate in front of every judge; a crash is recorded, never counted as a verdict."""
    spec = cases().get(key)
    if spec is None:
        raise SystemExit(f"{key}: no such judge case")
    work = out / key.replace("/", "_")
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    sam_before = sam_usage()
    row: dict = {"format": FORMAT, "case": key, "label": spec["label"], "why": spec["why"], "bug": spec["bug"],
                 "live": live, "decisions": {}, "reasons": {}}
    try:
        bug_patch = dev_variants()[spec["bug"]]
        candidate = (undo_patch(bug_patch, work / "candidate.patch") if spec["fixture"] is None
                     else FIXTURES / f"{spec['fixture']}.patch")
        verdict = {"format": "expectrail.verdict/v0", "spec": {"id": case_spec(spec["bug"])["id"],
                                                               "sha256": digest(case_spec(spec["bug"]))},
                   "observations": {"sha256": "0" * 64}, "result": "fail", "reason": "seeded bug",
                   "firstFrame": None, "evidence": [], "framesJudged": 0, "evaluator": dict(EVALUATOR)}
        request = build_repair_request(
            request_id=f"rr-judge-{key.replace('/', '-')}", spec=case_spec(spec["bug"]), verdict=verdict,
            route=load(SMOKE_ROUTE, "route"), base_patch=str(bug_patch.relative_to(REPO)), editable=EDITABLE,
            attempts=1)
        judges = [("expectrailNoSam", "trace")] + ([("expectrailSam", "sam")] if sam else [])
        for name, prov in judges:
            with provider(prov):
                v = verify(request, candidate, work / name)
            row["decisions"][name] = v["decision"]
            # Which checks failed, without the route they failed on (private routes have names).
            row["reasons"][name] = list(dict.fromkeys(r.split(" on ")[0] for r in (v.get("reasons") or [])))[:6]
        if glimmer:
            t_glimmer = time.perf_counter()
            decision, reasons = _glimmer_verify(request, candidate, work / "expectrailGlimmer")
            row["decisions"]["expectrailGlimmer"] = decision
            row["reasons"]["expectrailGlimmer"] = reasons
            row["glimmerSeconds"] = round(time.perf_counter() - t_glimmer, 1)
        if live:
            harness_run(SMOKE_ROUTE, work / "bugged", patches=[bug_patch])
            before = _frames(work / "bugged" / "frames")
            after = _frames(work / "expectrailNoSam" / "replay" / "frames")
            family = spec["bug"].split("/")[1]
            instruction = (f"A player reported: \"{REPORTS[family]}\" A developer changed the game to fix it. "
                           "The before frames show the bug and the after frames show the candidate fix, on the "
                           "same route at the same moments. Accept only if the reported problem is gone and "
                           "nothing else looks broken; otherwise reject.")
            judge = run_muse_judge(work / "muse-judge", before=before, after=after, instruction=instruction,
                                   sandboxed=True)
            row["decisions"]["museScreenshots"] = judge.get("decision")
            row["reasons"]["museScreenshots"] = [muse_reason(judge)]
        row["correct"] = {k: _correct(spec["label"], d) for k, d in row["decisions"].items()}
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        (work / "judge-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        row["error"] = f"{type(exc).__name__}: {exc}"[:300]
    row["wallClockSeconds"] = round(time.perf_counter() - t0, 1)
    row["samImages"] = sam_images_since(sam_before)  # only the SAM-on verification sends any
    (work / "result.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    return row


def summarize(out: Path) -> dict:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.rglob("result.json"))]
    rows = [r for r in rows if r.get("format") == FORMAT]
    per_judge = {}
    for j in [j for j in JUDGES if any(j in (r.get("decisions") or {}) for r in rows)]:
        decided = [r for r in rows if r["decisions"].get(j) in ("accept", "reject", "needs-review")]
        good = [r for r in decided if r["label"] == "good"]
        bad = [r for r in decided if r["label"] == "bad"]
        per_judge[j] = {
            "goodAccepted": sum(r["decisions"][j] == "accept" for r in good), "good": len(good),
            "badAccepted": sum(r["decisions"][j] == "accept" for r in bad), "bad": len(bad),
            "undecided": sum(1 for r in rows if j in r["decisions"] and r["decisions"][j] not in ("accept", "reject", "needs-review")),
        }
    doc = {"format": FORMAT + "-summary", "judges": per_judge,
           "rows": [{k: r.get(k) for k in ("case", "label", "why", "decisions", "error", "wallClockSeconds")}
                    for r in rows]}
    (out / "judge-summary.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def markdown(doc: dict) -> str:
    names = {"expectrailSam": "Expectrail, SAM on", "expectrailNoSam": "Expectrail, SAM off",
             "expectrailGlimmer": "Expectrail, Glimmer+engine", "museScreenshots": "Muse from screenshots"}
    shown = [j for j in JUDGES if j in doc["judges"]]
    lines = ["| Judge | Good fixes accepted | Bad fixes accepted | Undecided |", "| --- | --- | --- | --- |"]
    for j in shown:
        s = doc["judges"][j]
        lines.append(f"| {names[j]} | {s['goodAccepted']} of {s['good']} | {s['badAccepted']} of {s['bad']} | {s['undecided']} |")
    lines += ["", "| Case | Label | " + " | ".join(names[j] for j in shown) + " |",
              "| --- | --- | " + " | ".join("---" for _ in shown) + " |"]
    for r in doc["rows"]:
        lines.append(f"| {r['case']} | {r['label']} | " + " | ".join(str((r['decisions'] or {}).get(j, r.get('error') and 'error' or '-')) for j in shown) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--case")
    g.add_argument("--summarize", type=Path)
    p.add_argument("--out", type=Path, default=REPO / "runs" / "judge")
    p.add_argument("--live", action="store_true", help="also run Muse Code as the screenshot judge (spends credit)")
    p.add_argument("--no-sam", action="store_true", help="skip the SAM-on verifier (offline smoke runs)")
    p.add_argument("--glimmer", action="store_true",
                   help="also judge with Glimmer checked against the engine, as the judge ladder's fallback does")
    args = p.parse_args(argv)
    if args.list:
        print(json.dumps(sorted(cases())))
        return 0
    if args.summarize:
        print(markdown(summarize(args.summarize)))
        return 0
    row = run_case(args.case, args.out, live=args.live, sam=not args.no_sam, glimmer=args.glimmer)
    print(json.dumps({k: row.get(k) for k in ("case", "label", "decisions", "error", "wallClockSeconds")}))
    return 1 if row.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
