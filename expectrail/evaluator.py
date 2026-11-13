"""The reference evaluator: decides a test spec over SAM 3.1 observations, deterministically.

A model finds objects; this code decides whether the condition holds. Rules that matter:
  - an object that was looked for and not found is never a pass: the frame needs review, unless
    the assertion is about visibility itself;
  - every verdict names the spec and the observations it was computed from, by digest, so anyone
    can recompute it.

    python3 -m expectrail.evaluator --spec spec.json --observations obs.json [--out verdict.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from expectrail import __version__
from expectrail.contracts import digest, load
from expectrail.coverage import assess

EVALUATOR = {"name": "expectrail.evaluator", "version": __version__}
DEFAULT_MIN_SCORE = 0.5
MAX_EVIDENCE = 5


def _best(detections, min_score):
    found = [d for d in detections or [] if d.get("score", 0) >= min_score]
    return max(found, key=lambda d: d["score"]) if found else None


def _overlap(a, b, axis):
    lo, hi = (0, 2) if axis == "x" else (1, 3)
    return min(a[hi], b[hi]) - max(a[lo], b[lo]) > 0


def _distance(a, b):
    dx = max(b[0] - a[2], a[0] - b[2], 0)
    dy = max(b[1] - a[3], a[1] - b[3], 0)
    return (dx * dx + dy * dy) ** 0.5


EDGE = {"left": 0, "top": 1, "right": 2, "bottom": 3}
# side -> (index of the object's box coordinate to compare, sign): the object is on `side` of the
# boundary when sign * (coordinate - boundary) <= tolerance.
SIDE = {"above": (3, 1), "below": (1, -1), "left-of": (2, 1), "right-of": (0, -1)}


def _frames(spec, observations):
    window = spec.get("window", {})
    lo, hi = window.get("fromFrame", 0), window.get("toFrame")
    for frame in sorted(observations["frames"], key=lambda f: f["frame"]):
        if frame["frame"] >= lo and (hi is None or frame["frame"] <= hi):
            yield frame


def _assertion_verdict(spec: dict, observations: dict) -> dict:
    assertion = spec["assertion"]
    kind = assertion["type"]
    scores = {name: obj.get("minScore", DEFAULT_MIN_SCORE) for name, obj in spec["objects"].items()}

    def pick(frame, name):
        return _best(frame["objects"].get(name), scores.get(name, DEFAULT_MIN_SCORE))

    judged, missing, failures, first_fail = 0, [], [], None
    reached = None

    for frame in _frames(spec, observations):
        n = frame["frame"]
        obj = pick(frame, assertion["object"])
        if kind == "visible":
            judged += 1
            if obj is None:
                failures.append({"frame": n, "detail": f"{assertion['object']} not found"})
            continue
        if obj is None:
            missing.append(n)
            continue
        if kind == "inside-region":
            region = assertion["region"]
            if "box" in region:
                box = region["box"]
            else:
                ref = pick(frame, region["relativeTo"])
                if ref is None:
                    missing.append(n)
                    continue
                m = region.get("marginPx", 0)
                box = [ref["box"][0] - m, ref["box"][1] - m, ref["box"][2] + m, ref["box"][3] + m]
            judged += 1
            tol = assertion.get("tolerancePx", 0)
            b = obj["box"]
            if b[0] < box[0] - tol or b[1] < box[1] - tol or b[2] > box[2] + tol or b[3] > box[3] + tol:
                failures.append({"frame": n, "detail": f"{assertion['object']} {b} leaves region {box}",
                                 "boxes": {assertion["object"]: b, "region": box}})
        elif kind == "never-crosses":
            bnd = assertion["boundary"]
            index, sign = SIDE[bnd["side"]]
            tol = bnd.get("tolerancePx", 0)
            if "relativeTo" in bnd:
                refs = [d for d in frame["objects"].get(bnd["relativeTo"]) or []
                        if d.get("score", 0) >= scores.get(bnd["relativeTo"], DEFAULT_MIN_SCORE)]
                if not refs:
                    missing.append(n)
                    continue
                if bnd.get("requireOverlap", True):
                    other = "x" if bnd["side"] in ("above", "below") else "y"
                    refs = [d for d in refs if _overlap(obj["box"], d["box"], other)]
                    if not refs:
                        continue  # nothing under (or beside) the object in this frame: not applicable
                ref = min(refs, key=lambda d: abs(d["box"][EDGE[bnd["edge"]]] - obj["box"][index]))
                value = ref["box"][EDGE[bnd["edge"]]]
                boxes = {assertion["object"]: obj["box"], bnd["relativeTo"]: ref["box"]}
            else:
                value = bnd["value"]
                boxes = {assertion["object"]: obj["box"]}
            judged += 1
            past = sign * (obj["box"][index] - value)
            if past > tol:
                failures.append({"frame": n, "detail": f"{assertion['object']} is {past:g}px past the boundary "
                                 f"({bnd['side']} {value:g}, tolerance {tol:g})", "boxes": boxes})
        elif kind == "reaches":
            goal = pick(frame, assertion["goal"])
            if goal is None:
                missing.append(n)
                continue
            judged += 1
            if _distance(obj["box"], goal["box"]) <= assertion.get("distancePx", 0):
                if reached is None:
                    reached = n
        else:
            raise ValueError(f"unsupported assertion type: {kind}")

    if failures:
        first_fail = failures[0]["frame"]
    if kind == "visible":
        frac = 1 - len(failures) / judged if judged else 0.0
        need = assertion.get("minFraction", 1.0)
        if not judged:
            result, reason = "needs-review", "no frames observed in the window"
        elif frac >= need:
            result, reason = "pass", f"{assertion['object']} found in {judged - len(failures)} of {judged} frames"
        else:
            result, reason = "fail", (f"{assertion['object']} found in {judged - len(failures)} of {judged} "
                                      f"frames; needs {need:.0%}")
    elif kind == "reaches":
        if reached is not None:
            result, reason = "pass", f"{assertion['object']} reached {assertion['goal']} at frame {reached}"
        elif missing:
            result, reason = "needs-review", (f"{assertion['object']} did not reach {assertion['goal']} in the "
                                              f"frames judged, and {len(missing)} frames are missing an object")
        elif judged:
            result, reason = "fail", f"{assertion['object']} never reached {assertion['goal']} in {judged} frames"
        else:
            result, reason = "needs-review", "no frames observed in the window"
    else:
        if failures:
            result, reason = "fail", failures[0]["detail"] + f" (first at frame {first_fail}, {len(failures)} frames)"
        elif missing:
            result, reason = "needs-review", (f"no violation in {judged} frames judged, but an object was not "
                                              f"found in {len(missing)} frames (first {missing[0]}); a missing "
                                              f"object is never a pass")
        elif judged:
            result, reason = "pass", f"no violation in {judged} frames"
        else:
            result, reason = "needs-review", "no frame had the objects needed to judge this assertion"

    return {
        "format": "expectrail.verdict/v0",
        "spec": {"id": spec["id"], "sha256": digest(spec)},
        "observations": {"sha256": digest(observations)},
        "result": result,
        "reason": reason,
        "firstFrame": first_fail if result == "fail" else None,
        "evidence": failures[:MAX_EVIDENCE],
        "framesJudged": judged,
        "evaluator": dict(EVALUATOR),
    }


def evaluate(spec: dict, observations: dict, *, route: str | None = None, trace: dict | None = None,
             expected_frames: list[int] | None = None) -> dict:
    """Judge the unchanged assertion, then require exercised coverage before counting its pass."""
    # A duplicated observation is not another judged frame.
    frames = observations.get("frames", [])
    if len({f["frame"] for f in frames}) != len(frames):
        raise ValueError("observations contain duplicate frame numbers")
    verdict = _assertion_verdict(spec, observations)
    coverage, detail = assess(spec, observations, verdict["framesJudged"], counterexample=verdict["result"] == "fail",
                              route=route, trace=trace, expected_frames=expected_frames)
    verdict["coverage"] = coverage
    if coverage["status"] == "not-applicable":
        verdict.update(result="not-applicable", reason="not-applicable: this spec does not apply to this route",
                       firstFrame=None, evidence=[], framesJudged=0)
    elif coverage["semanticResult"] not in ("pass", "fail"):
        verdict.update(result="needs-review", reason="not-exercised: " + detail + "; " + verdict["reason"],
                       firstFrame=None)
    return verdict


REQUIRED_CHECK_KINDS = frozenset({"regression", "gameplay", "held-out", "clean"})


def decide(checks: list[dict]) -> tuple[str, list[str]]:
    """Accept only when every required kind is present and every check passes.

    Order: empty → any fail (reject) → missing required kinds (needs-review) →
    any needs-review → accept. Kind completeness is a set, not a row count.
    """
    checks = [c for c in checks if c["result"] != "not-applicable"]
    fails = [c for c in checks if c["result"] == "fail"]
    unclear = [c for c in checks if c["result"] == "needs-review"]
    if not checks:
        return "needs-review", ["no checks ran"]
    if fails:
        return "reject", [f"{c['kind']} check {c['spec']} failed on {c['route']}" for c in fails]
    present = {c["kind"] for c in checks}
    missing = sorted(REQUIRED_CHECK_KINDS - present)
    if missing:
        return "needs-review", [f"missing required check kinds: {', '.join(missing)}"]
    if unclear:
        return "needs-review", [f"{c['kind']} check {c['spec']} needs review on {c['route']}" for c in unclear]
    return "accept", [f"all {len(checks)} checks passed"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Decide a test spec over SAM observations.")
    p.add_argument("--spec", type=Path, required=True)
    p.add_argument("--observations", type=Path, required=True)
    p.add_argument("--out", type=Path)
    p.add_argument("--route", help="route name for coverage applicability")
    p.add_argument("--trace", type=Path, help="engine trace for declared route checkpoints")
    args = p.parse_args(argv)
    trace = json.loads(args.trace.read_text(encoding="utf-8")) if args.trace else None
    verdict = evaluate(load(args.spec, "test-spec"), load(args.observations, "observations"), route=args.route, trace=trace)
    text = json.dumps(verdict, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(f"{verdict['result']}: {verdict['reason']}")
    return {"pass": 0, "fail": 1, "needs-review": 2, "not-applicable": 2}[verdict["result"]]


if __name__ == "__main__":
    sys.exit(main())
