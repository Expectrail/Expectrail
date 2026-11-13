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

A second way to judge, added after the first clean routes the range was held against (one clean
frame in 36 was out: the robot in front of a tree, answered as robot and trunk together, for nine
frames in a row):

    pair        every frame of a changed game against the same frame of the unchanged game on the
                same route. Where the engine puts the player in the same place in both, the two
                boxes must agree within ``tolerance``. Where it does not, this rule has nothing to
                compare and says so. The unchanged game's own slips are in both and cancel.

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
# For pairs. How far a measure may differ between the unchanged game's box and the changed game's,
# in game pixels. The largest difference in the recorded answers between two runs that show the
# same robot in the same place (clean and missing-texture, 13 frames) is 5 px, once, in the width;
# the rest are 1.5 px or less. The sinking bug moves two measures by 25.5 px or more in every frame.
# A drawing moved by 6 px or less is not seen at this value.
DEFAULT_TOLERANCE = 6.0
# For pairs. How far the confidence may fall below the unchanged game's for the same frame. In the
# recorded answers the same robot in the same place never fell by more than 0.031 (52 frame pairs,
# point and box). Asked with a box, the sinking bug fell by 0.23 to 0.56 in every frame and the
# hidden robot by 0.32 to 0.53 in every frame it is hidden in. Asked with a point the confidence
# is far less steady from frame to frame, but a harmless change still lowered it by 0.031 at most.
# Only a fall counts: a change that makes the player easier to see is not this rule's business.
DEFAULT_DROP = 0.1
# The engine's player position, in game pixels, must agree this closely for two frames to be the
# same place. The trace is written to a hundredth of a pixel.
SAME_PLACE = 0.05


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


def pair_frame(base: dict | None, head: dict, tolerance: float, drop: float = DEFAULT_DROP) -> dict:
    """One frame of the changed game against the same frame of the unchanged game.

    States: in, out, moved (the engine puts the player somewhere else, so there is nothing to
    compare), no-base (the unchanged game has no box for this frame), no-answer, not-asked.
    """
    out = {"frame": head["frame"]}
    if not head.get("asked"):
        return {**out, "state": "not-asked", "why": [head.get("note") or "not asked"]}
    if base is None or not base.get("asked") or not base.get("box"):
        return {**out, "state": "no-base", "why": ["the unchanged game has no box for this frame"]}
    (bx, by), (hx, hy) = base["world"], head["world"]
    if abs(bx - hx) > SAME_PLACE or abs(by - hy) > SAME_PLACE:
        return {**out, "state": "moved", "why": [f"the engine has the player at {hx:g}, {hy:g}; unchanged, at {bx:g}, {by:g}"]}
    if not head.get("box"):
        return {**out, "state": "no-answer", "why": [head.get("error") or head.get("note") or "no box came back"]}
    why = []
    if bool(head.get("holdsPoint")) != bool(base.get("holdsPoint")):
        why.append("the box holds the point in one game and not in the other")
    was, now = measures(base), measures(head)
    for name in MEASURES:
        if abs(now[name] - was[name]) > tolerance:
            why.append(f"{name} {now[name]:g} against {was[name]:g} unchanged")
    # A confidence is compared only where both games' answers have one: a missing score is not a zero.
    if base.get("score") is not None and head.get("score") is not None and base["score"] - head["score"] > drop + 1e-9:
        why.append(f"confidence {head['score']:.2f} against {base['score']:.2f} unchanged")
    return {**out, "state": "out" if why else "in", "why": why}


def different_route(base: dict | None, head: dict | None) -> str | None:
    """Why two runs are not the same route, or None when they are or when either does not say.
    The digest decides when both have one; otherwise the name."""
    if not base or not head:
        return None
    key = "sha256" if base.get("sha256") and head.get("sha256") else "name"
    if base.get(key) == head.get(key):
        return None
    return f"a different route ({head.get('name')} against {base.get('name')})"


def pair(base_run: dict, head_run: dict, tolerance: float = DEFAULT_TOLERANCE, drop: float = DEFAULT_DROP) -> dict:
    """A changed game's run against the unchanged game's run of the same route.

    Fail on the first frame out. A pass needs every asked frame compared and in: a frame the engine
    moved, a frame the unchanged game has no box for, or a frame with no answer leaves the run at
    needs-review, because this rule then says nothing about it and silence is never a pass.
    """
    if tolerance < 0 or drop < 0:
        raise RuleError("the tolerance and the confidence drop cannot be negative")
    states = ("in", "out", "moved", "no-base", "no-answer", "not-asked")
    other = different_route(base_run.get("route"), head_run.get("route"))
    if other:
        # The same place on another route is another moment of play: the pose need not be the same.
        return {"run": head_run.get("run"), "result": "needs-review", "judged": 0, **{s: 0 for s in states}, "frames": [],
                "reason": f"{other}: frames of different routes are not compared, and that is not a pass"}
    base = {r["frame"]: r for r in base_run.get("frames") or []}
    frames = [pair_frame(base.get(r["frame"]), r, tolerance, drop) for r in head_run.get("frames") or []]
    count = {state: sum(1 for f in frames if f["state"] == state) for state in states}
    judged = count["in"] + count["out"]
    first = next((f for f in frames if f["state"] == "out"), None)
    unjudged = count["moved"] + count["no-base"] + count["no-answer"]
    if first is not None:
        result = "fail"
        reason = (f"{count['out']} of {judged} compared frames differ from the unchanged game, first frame "
                  f"{first['frame']}: {'; '.join(first['why'])}")
    elif unjudged or not judged:
        result = "needs-review"
        parts = []
        if count["moved"]:
            parts.append(f"the engine puts the player elsewhere in {count['moved']} frames")
        if count["no-base"]:
            parts.append(f"the unchanged game has no box for {count['no-base']}")
        if count["no-answer"]:
            parts.append(f"{count['no-answer']} got no box")
        if not parts:
            parts.append("no frame was asked about in both games")
        reason = "; ".join(parts) + f"; {judged} frames were compared and agree, and that is not a pass"
    else:
        result = "pass"
        reason = (f"all {judged} asked frames agree with the unchanged game within {tolerance:g} px and "
                  f"{drop:g} of its confidence")
    return {"run": head_run.get("run"), "result": result, "reason": reason, "judged": judged, **count, "frames": frames}


def pairs_markdown(base_name: str, tolerance: float, lift, results: list[dict], drop: float = DEFAULT_DROP) -> str:
    lines = ["# The anchored rule, in pairs: each frame against the unchanged game's same frame", "",
             f"Unchanged game: `{base_name}`. Tolerance {tolerance:g} game px, confidence may fall by {drop:g}"
             + (f", point {lift:g} px above the origin" if lift is not None else "")
             + ". A probe's rule: no verdict reads it.", "",
             "| Run | Result | Compared | Differ | Engine moved | No base | No answer | Not asked | Why |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for res in results:
        lines.append(f"| {res['run']} | {res['result']} | {res['judged']} | {res['out']} | {res['moved']} | "
                     f"{res['no-base']} | {res['no-answer']} | {res['not-asked']} | {res['reason'].replace('|', '/')} |")
    return "\n".join(lines) + "\n"


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
    how = p.add_mutually_exclusive_group(required=True)
    how.add_argument("--calibrate", metavar="FILE[:RUN]",
                     help="the anchor.json and the clean run in it that sets the range")
    how.add_argument("--pair", metavar="FILE[:RUN]",
                     help="the anchor.json and the unchanged game's run in it: judge every other run frame by "
                          "frame against it (the runs must be the same route)")
    p.add_argument("--drop", type=float, default=DEFAULT_DROP,
                   help=f"with --pair, how far the confidence may fall below the unchanged game's (default {DEFAULT_DROP:g})")
    p.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                   help=f"with --pair, how far a measure may differ, in game pixels (default {DEFAULT_TOLERANCE:g})")
    p.add_argument("--judge", type=Path, nargs="+", required=True, metavar="FILE", help="anchor.json files to judge, every run")
    p.add_argument("--pad", type=float, default=DEFAULT_PAD,
                   help=f"widen every range by this many game pixels (default {DEFAULT_PAD:g})")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    if args.pair:
        return _main_pairs(args)
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
            _same_question(file, doc, report)
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


def _same_question(file, doc: dict, report: dict) -> None:
    """Answers to a point and answers to a box, or to boxes of two sizes, are not the same question."""
    if (doc.get("box"), doc.get("pad")) != (report.get("box"), report.get("pad")):
        def said(d):
            b = d.get("box")
            if b == "body":
                return f"the player's own box widened by {d.get('pad'):g}"
            return "a point" if not b else f"a box of {b[0]:g} x {b[1]:g}"
        raise RuleError(f"{file} was asked with {said(doc)} and the other report with "
                        f"{said(report)}: answers to different questions cannot be compared")


def _main_pairs(args) -> int:
    path, _, name = args.pair.partition(":")
    try:
        report, base = load_run(Path(path), name or None)
        results = []
        for file in args.judge:
            doc = load_report(file)
            if doc.get("lift") != report.get("lift"):
                raise RuleError(f"{file} was asked {doc.get('lift')} px above the origin and the unchanged game "
                                f"{report.get('lift')}: boxes asked at different points cannot be compared")
            _same_question(file, doc, report)
            same_file = Path(file).resolve() == Path(path).resolve()
            results += [pair(base, run, args.tolerance, args.drop) for run in doc["runs"]
                        if not (same_file and run.get("run") == base.get("run"))]
    except RuleError as exc:
        print(f"anchored rule: {exc}", file=sys.stderr)
        return 2
    page = pairs_markdown(base.get("run"), args.tolerance, report.get("lift"), results, args.drop)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "anchor-pairs.md").write_text(page, encoding="utf-8")
        (args.out / "anchor-pairs.json").write_text(json.dumps(
            {"base": base.get("run"), "tolerance": args.tolerance, "drop": args.drop, "lift": report.get("lift"),
             "box": report.get("box"), "results": results},
            indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.out / 'anchor-pairs.md'}")
    else:
        print(page, end="")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for res in results[:9]:
            print(f"::notice title=Anchored pairs {res['run']}::{_escape(res['result'] + ': ' + res['reason'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
