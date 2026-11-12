"""A rule over the anchored probe's answers: is what is drawn at the player's place the player? (#330)

The anchored probe (agents/sam_anchor.py) asks SAM what is drawn at the engine's player position
and measures the box that comes back. This turns those measurements into a result, the way Sean
agreed on November 12, 2026:

    one box holding the point, its size and its reach above and below the point inside the range
    a clean run sets. Confidence is not part of it: on the clean game it dips to 0.50 and the
    sinking bug scores 0.92.

Two steps, both plain arithmetic over an ``anchor.json``:

    calibrate   from a clean run: the smallest and largest width, height, reach above and reach
                below of its boxes, in game pixels, each widened by ``pad``.
    judge       every asked frame of a run against those ranges.

A frame is ``out`` when its box does not hold the point or any of the four measures is outside its
range. A run fails on its first frame that is out. A frame that was asked and got no box is never
a pass: with no frame out, the run is needs-review. Frames the probe did not ask about (the player
outside the picture) are not judged, and a run with none judged is needs-review.

**This decides nothing in the product.** No verdict reads it. It exists to be measured: set on one
clean route and held against other clean routes (the false alarms) and against the seeded bugs.

    python3 -m agents.anchor_rule --calibrate runs/sam-probe/anchor.json:clean \\
        --judge runs/sam-probe/anchor.json --out runs/sam-probe

Writes <out>/anchor-rule.md and <out>/anchor-rule.json. Sends nothing anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

MEASURES = ("width", "height", "above", "below")
# How far every range is widened, in game pixels, unless told otherwise. From the recorded answers
# (tests/data/sam-anchor): the bundled game's clean run and its missing-texture run show the same
# robot in the same frames with only the coins different, and between them a box's height and its
# reach moved by up to 1.5 px (its width by 5 px, once in 13 frames). With no pad the clean run has
# a frame outside the range the missing-texture run sets. It is a starting value, not a tuned one.
DEFAULT_PAD = 2.0


class RuleError(ValueError):
    """The rule cannot be set or applied to this input. Never a result."""


def measures(row: dict) -> dict:
    """The four numbers the rule reads from one answered frame, in game pixels."""
    return {"width": row["worldSize"][0], "height": row["worldSize"][1],
            "above": row["aboveOrigin"], "below": row["belowOrigin"]}


def load_report(path: Path) -> dict:
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(report["runs"], list):
            raise TypeError("runs")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuleError(f"{path}: not an anchored probe's report ({type(exc).__name__})") from exc
    return report


def load_run(path: Path, name: str | None = None) -> tuple[dict, dict]:
    """(the report, one run of it). With no name the report must hold exactly one run."""
    report = load_report(path)
    runs = report["runs"]
    if name is None:
        if len(runs) != 1:
            raise RuleError(f"{path} holds {len(runs)} runs; name one, as FILE:RUN")
        return report, runs[0]
    for run in runs:
        if run.get("run") == name:
            return report, run
    raise RuleError(f"{path} has no run named {name!r} (it has {', '.join(r.get('run', '?') for r in runs)})")


def calibrate(run: dict, pad: float = DEFAULT_PAD, lift: float | None = None) -> dict:
    """The ranges a clean run sets. Refused unless every asked frame got a box that holds its point:
    a clean run that the observer cannot read is not a yardstick."""
    if pad < 0:
        raise RuleError("the pad cannot be negative")
    asked = [r for r in run.get("frames") or [] if r.get("asked")]
    if not asked:
        raise RuleError(f"{run.get('run')}: no frame was asked about, so there is nothing to set a range from")
    bad = [r["frame"] for r in asked if not r.get("box") or not r.get("holdsPoint")]
    if bad:
        raise RuleError(f"{run.get('run')}: frames {bad} got no box holding the point; a clean run the observer "
                        "cannot read sets no range")
    ranges = {}
    for name in MEASURES:
        values = [measures(r)[name] for r in asked]
        ranges[name] = [round(min(values) - pad, 3), round(max(values) + pad, 3)]
    return {"from": run.get("run"), "frames": [r["frame"] for r in asked], "pad": pad, "lift": lift, "ranges": ranges}


def judge_frame(row: dict, ranges: dict) -> dict:
    """One frame: {"frame", "state": in | out | no-answer | not-asked, "why": [...]}."""
    out = {"frame": row["frame"]}
    if not row.get("asked"):
        return {**out, "state": "not-asked", "why": [row.get("note") or "not asked"]}
    if not row.get("box"):
        return {**out, "state": "no-answer", "why": [row.get("error") or row.get("note") or "no box came back"]}
    why = []
    if not row.get("holdsPoint"):
        why.append("the box does not hold the point")
    for name, value in measures(row).items():
        lo, hi = ranges[name]
        if not lo <= value <= hi:
            why.append(f"{name} {value:g} (clean {lo:g} to {hi:g})")
    return {**out, "state": "out" if why else "in", "why": why}


def judge(run: dict, calibration: dict) -> dict:
    """A run against a calibration: fail on the first frame out, never a pass on a frame with no answer."""
    frames = [judge_frame(r, calibration["ranges"]) for r in run.get("frames") or []]
    count = {state: sum(1 for f in frames if f["state"] == state) for state in ("in", "out", "no-answer", "not-asked")}
    judged = count["in"] + count["out"]
    first = next((f for f in frames if f["state"] == "out"), None)
    if first is not None:
        result = "fail"
        reason = (f"{count['out']} of {judged} judged frames are outside the clean range, first frame "
                  f"{first['frame']}: {'; '.join(first['why'])}")
    elif count["no-answer"]:
        result = "needs-review"
        reason = f"{count['no-answer']} asked frames got no box; a missing answer is never a pass"
    elif not judged:
        result = "needs-review"
        reason = "no frame could be judged: the player was never asked about"
    else:
        result = "pass"
        reason = f"all {judged} judged frames are inside the clean range"
    return {"run": run.get("run"), "result": result, "reason": reason, "judged": judged, **count, "frames": frames}


def markdown(calibration: dict, results: list[dict]) -> str:
    r = calibration["ranges"]
    lines = ["# The anchored rule: what is drawn at the player's place, against a clean run's range", "",
             f"Set on `{calibration['from']}` ({len(calibration['frames'])} frames, pad {calibration['pad']:g} game px"
             + (f", point {calibration['lift']:g} px above the origin" if calibration.get("lift") is not None else "")
             + "). A probe's rule: no verdict reads it.", "",
             "| Measure (game px) | From | To |", "| --- | --- | --- |"]
    lines += [f"| {name} | {r[name][0]:g} | {r[name][1]:g} |" for name in MEASURES]
    lines += ["", "| Run | Result | Judged | Out | No answer | Not asked | Why |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for res in results:
        lines.append(f"| {res['run']} | {res['result']} | {res['judged']} | {res['out']} | {res['no-answer']} | "
                     f"{res['not-asked']} | {res['reason'].replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Judge an anchored probe's answers against a clean run's range.")
    p.add_argument("--calibrate", required=True, metavar="FILE[:RUN]",
                   help="the anchor.json and the clean run in it that sets the range")
    p.add_argument("--judge", type=Path, nargs="+", required=True, metavar="FILE", help="anchor.json files to judge, every run")
    p.add_argument("--pad", type=float, default=DEFAULT_PAD,
                   help=f"widen every range by this many game pixels (default {DEFAULT_PAD:g})")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    path, _, name = args.calibrate.partition(":")
    try:
        report, clean = load_run(Path(path), name or None)
        calibration = calibrate(clean, args.pad, report.get("lift"))
        results = []
        for file in args.judge:
            doc = load_report(file)
            if doc.get("lift") != report.get("lift"):
                raise RuleError(f"{file} was asked {doc.get('lift')} px above the origin and the range was set at "
                                f"{report.get('lift')}: a reach measured from another point cannot be compared")
            results += [judge(run, calibration) for run in doc["runs"]]
    except RuleError as exc:
        print(f"anchored rule: {exc}", file=sys.stderr)
        return 2
    page = markdown(calibration, results)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "anchor-rule.md").write_text(page, encoding="utf-8")
        (args.out / "anchor-rule.json").write_text(
            json.dumps({"calibration": calibration, "results": results}, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.out / 'anchor-rule.md'}")
    else:
        print(page, end="")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for res in results[:9]:
            print(f"::notice title=Anchored rule {res['run']}::{_escape(res['result'] + ': ' + res['reason'])}")
        r = calibration["ranges"]
        print("::notice title=Anchored rule range::" + _escape(
            f"set on {calibration['from']}, pad {calibration['pad']:g}; "
            + "; ".join(f"{n} {r[n][0]:g} to {r[n][1]:g}" for n in MEASURES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
