"""Where two replays of one Unity route differ, field by field: the cross-runner determinism check.

``harness.unity.run --compare`` says whether two replays are identical (frame hashes and the trace's
sha256). When they are not, this says where: which top-level trace sections differ, and for the
route's rows, each field's first differing tick, how many ticks differ and the largest numeric gap;
the frames that differ; and the settle each replay held before tick 0 (replay.json), which is not in
the trace. The frame of a tick a real-time fade starts on may differ, when both replays saw the same
fades start at the same ticks (the harness holds game time from there). Unity runs 8 and 9 (42716741830, 42722765528) replayed the same route identically within
each run but gave different trace hashes across runs, built and replayed on different machines.

    python3 -m harness.unity.trace_diff RUN_A RUN_B [--json OUT]

RUN_A and RUN_B are replay directories with trace.json and replay.json (and machine.txt if the
workflow wrote one). Exit 0 when the route (rows and frames) and the rest of the trace (the level's
geometry and art) are identical, 1 when anything differs, so the settle hold alone never fails it.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROW_FIELDS_ORDER = ("tick", "frame", "player", "onFloor", "facing", "ground", "coins", "enemies",
                    "projectiles", "view", "objects")


def _numbers(value) -> list[float]:
    """Every number in a value, in order (booleans excluded), for the largest gap between two values."""
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict):
        return [n for k in sorted(value) for n in _numbers(value[k])]
    if isinstance(value, list):
        return [n for v in value for n in _numbers(v)]
    return []


def _gap(a, b) -> float | None:
    na, nb = _numbers(a), _numbers(b)
    if not na or len(na) != len(nb):
        return None
    gaps = [abs(x - y) for x, y in zip(na, nb) if math.isfinite(x) and math.isfinite(y)]
    return max(gaps) if gaps else None


def _objects_by_id(row: dict) -> dict[str, dict]:
    return {o["id"]: o for o in row.get("objects") or []}


def diff_rows(rows_a: list[dict], rows_b: list[dict]) -> dict:
    """Per field: the first tick where the two replays differ, how many ticks differ, the largest gap."""
    fields: dict[str, dict] = {}
    count = min(len(rows_a), len(rows_b))
    names = [f for f in ROW_FIELDS_ORDER] + sorted(
        {k for r in rows_a + rows_b for k in r} - set(ROW_FIELDS_ORDER))
    for name in names:
        ticks: list[int] = []
        gap: float | None = None
        first = None
        for i in range(count):
            a, b = rows_a[i].get(name), rows_b[i].get(name)
            if name == "objects":
                a, b = _objects_by_id(rows_a[i]), _objects_by_id(rows_b[i])
            if a == b:
                continue
            ticks.append(rows_a[i].get("tick", i))
            g = _gap(a, b)
            if g is not None:
                gap = g if gap is None else max(gap, g)
            if first is None:
                first = {"tick": rows_a[i].get("tick", i), "a": a, "b": b} if name != "objects" else {
                    "tick": rows_a[i].get("tick", i),
                    "ids": sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))[:5]}
        if ticks:
            fields[name] = {"ticksDiffer": len(ticks), "firstTick": ticks[0], "largestGap": gap, "first": first}
    return {"rows": [len(rows_a), len(rows_b)], "fields": fields}


def diff(run_a: Path, run_b: Path) -> dict:
    trace_a, trace_b = (json.loads((r / "trace.json").read_text(encoding="utf-8")) for r in (run_a, run_b))
    rep_a, rep_b = (json.loads((r / "replay.json").read_text(encoding="utf-8")) for r in (run_a, run_b))
    sections = sorted((set(trace_a) | set(trace_b)) - {"rows"})
    frames_a, frames_b = rep_a.get("frameSha256") or [], rep_b.get("frameSha256") or []
    frames = [i for i in range(max(len(frames_a), len(frames_b)))
              if i >= len(frames_a) or i >= len(frames_b) or frames_a[i] != frames_b[i]]
    rows = diff_rows(trace_a.get("rows") or [], trace_b.get("rows") or [])
    # The frame of a tick a real-time fade starts on can differ (the fade's first step is real time);
    # the harness holds game time from there, so only those frames, and only when both replays saw the
    # same fades start at the same ticks.
    starts = [sorted(h["tick"] for h in r.get("hazards") or []
                     if h.get("kind") == "real-time-fade-during-route" and h.get("tick") is not None)
              for r in (rep_a, rep_b)]
    allowed = set(starts[0]) if starts[0] == starts[1] else set()
    unexplained = [i for i in frames if i not in allowed]
    machine = [next((p.read_text(encoding="utf-8").strip() for p in (r / "machine.txt", r.parent / "machine.txt")
                     if p.is_file()), None) for r in (run_a, run_b)]
    route_same = not unexplained and not rows["fields"] and rows["rows"][0] == rows["rows"][1] and starts[0] == starts[1]
    return {
        "machines": machine,
        "traceSha256": [rep_a.get("trace", {}).get("sha256"), rep_b.get("trace", {}).get("sha256")],
        "sectionsDiffer": [s for s in sections if trace_a.get(s) != trace_b.get(s)],
        "rows": rows,
        "frames": {"count": [len(frames_a), len(frames_b)], "differ": len(frames), "first": frames[0] if frames else None,
                   "atFadeStarts": len(frames) - len(unexplained), "unexplained": len(unexplained)},
        "fadeStarts": starts,
        "settle": [rep_a.get("settle"), rep_b.get("settle")],
        "routeIdentical": route_same,
    }


def summary(d: dict) -> str:
    rows = d["rows"]["fields"]
    parts = [f"route {'identical' if d['routeIdentical'] else 'DIFFERS'}",
             f"frames differing {d['frames']['differ']} of {max(d['frames']['count'])}"
             + (f" (first {d['frames']['first']})" if d["frames"]["first"] is not None else "")
             + f", {d['frames']['atFadeStarts']} of them on a fade's first tick",
             "fade starts " + " vs ".join(str(s) for s in d["fadeStarts"]),
             "row fields differing: " + (", ".join(
                 f"{k} on {v['ticksDiffer']} ticks from tick {v['firstTick']}"
                 + (f", largest gap {v['largestGap']:.4g}" if v["largestGap"] is not None else "")
                 for k, v in rows.items()) or "none"),
             "other trace sections differing: " + (", ".join(d["sectionsDiffer"]) or "none"),
             "settle " + " vs ".join(f"{s.get('ticks')} ticks/{s.get('frozenFrames')} held" if s else "none"
                                     for s in d["settle"])]
    return "; ".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run_a", type=Path)
    ap.add_argument("run_b", type=Path)
    ap.add_argument("--json", type=Path, help="write the full difference here")
    args = ap.parse_args(argv)
    d = diff(args.run_a, args.run_b)
    if args.json:
        args.json.write_text(json.dumps(d, indent=1, default=str) + "\n", encoding="utf-8")
    print(summary(d))
    return 0 if d["routeIdentical"] and not d["sectionsDiffer"] else 1


if __name__ == "__main__":
    sys.exit(main())
