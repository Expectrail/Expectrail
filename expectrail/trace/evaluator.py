"""The bounded trace-contract interpreter (docs/discovery.md, operator semantics).

A trace-spec is one closed, typed operation; this module is the only thing that gives it meaning.
Model output never contains code: a model can only choose an operation and its parameters, and the
schema refuses anything else. Evaluation is pure: no model calls, no files, no game.

Every evaluation returns one of five results, with counts:

- **pass**: applicable, triggered and evaluated at least as often as the spec requires, the
  window completely observed, and no counterexample;
- **fail**: a concrete counterexample in observed data, even if other parts are incomplete;
- **not_exercised**: nothing triggered the obligation (no bullets, no jump, no movement). It is
  never a pass: a rule that never fires has said nothing;
- **insufficient_observation**: the scope or required data cannot be established;
- **execution_error**: the evaluation itself failed.

``relation`` compares one signal between two episodes, a probe and its transformed twin (more air
presses, faster taps, the mirrored direction). It is the one addition to the specification's eight
operators: it takes its bound from the game's own behaviour on the twin probe, so it needs no number
from a person or a healthy reference build.
"""
from __future__ import annotations

import math
import traceback

from expectrail.contracts import digest_v1, validate_v1
from expectrail.coverage import evidence_result
from expectrail.trace import signals

EVALUATOR = {"name": "expectrail.trace.evaluator", "version": "1.0.0"}
RESULTS = ("pass", "fail", "not_exercised", "insufficient_observation", "execution_error")


class _Eval:
    def __init__(self, spec: dict, episodes: list[dict]):
        self.spec = spec
        self.episodes = episodes
        self.triggered = self.evaluated = self.excluded = 0
        self.metrics: dict = {}
        self.evidence: list[dict] = []
        self.diagnostics: list[str] = []
        self.applicable = "yes"
        self.complete = True
        self.counterexample = False

    def note(self, ep: dict, a: int, b: int, detail: str) -> None:
        if len(self.evidence) < 8:
            self.evidence.append({"episodeId": ep["id"], "fromTick": int(a), "toTick": int(b), "detail": detail})

    def verdict(self, result: str | None = None) -> dict:
        req = self.spec["evidenceRequirement"]
        if result is None:
            result = evidence_result(counterexample=self.counterexample, applicable=self.applicable,
                                     triggered=self.triggered, evaluated=self.evaluated,
                                     minimum_triggers=req["minimumTriggers"],
                                     minimum_evaluations=req["minimumEvaluations"], complete=self.complete,
                                     complete_window=req["completeWindow"])
        return {
            "format": "expectrail.trace-verdict/v1",
            "specId": self.spec["id"],
            "specSha256": digest_v1(self.spec),
            "episodeIds": [ep["id"] for ep in self.episodes],
            "evaluator": dict(EVALUATOR),
            "result": result,
            "applicable": self.applicable,
            "triggeredCount": self.triggered,
            "evaluatedCount": self.evaluated,
            "excludedCount": self.excluded,
            "coverageComplete": bool(self.complete and self.applicable == "yes"),
            "metrics": {k: (None if v is None else (round(v, 4) if isinstance(v, float) else v))
                        for k, v in self.metrics.items()},
            "evidence": self.evidence,
            "diagnostics": self.diagnostics,
        }


def _window(spec: dict, ep: dict) -> tuple[list[dict], bool]:
    """The samples inside the spec's window, and whether that window was completely observed."""
    w = spec["window"]
    first, last = ep["completeness"]["firstTick"], ep["completeness"]["lastTick"]
    lo, hi = (first, last) if w["kind"] == "episode" else (w["fromTick"], w["toTick"])
    inside = [s for s in ep["samples"] if lo <= s["tick"] <= hi]
    gaps = [g for g in ep["completeness"]["gaps"] if not (g[1] < lo or g[0] > hi)]
    complete = bool(inside) and lo >= first and hi <= last and not gaps
    return inside, complete


def _cap(ep: dict, cls: str) -> str:
    if cls == "player":
        return "complete" if ep["capabilities"]["player"] else "absent"
    return ep["capabilities"]["enemies" if cls == "enemy" else "projectiles"]


def _ticks(seconds: float, tps: int, *, bound: str) -> int:
    value = seconds * tps
    return int(math.ceil(value - 1e-9)) if bound == "min" else int(math.floor(value + 1e-9))


# --- operators ----------------------------------------------------------------------------------


def _min_event_interval(e: _Eval, ep: dict, op: dict) -> None:
    samples, e.complete = _window(e.spec, ep)
    lo, hi = samples[0]["tick"], samples[-1]["tick"]
    if _cap(ep, "projectile") == "unknown":
        e.applicable = "unknown"
    ticks = sorted(ev["tick"] for ev in ep["events"] if ev["type"] == op["event"] and lo <= ev["tick"] <= hi)
    min_gap = _ticks(op["seconds"], ep["physicsTicksPerSecond"], bound="min")
    e.metrics.update(minIntervalTicks=min_gap, events=len(ticks))
    e.triggered = len(ticks)
    gaps = [(a, b) for a, b in zip(ticks, ticks[1:])]
    e.evaluated = len(gaps)
    if gaps:
        shortest = min(b - a for a, b in gaps)
        e.metrics["shortestGapTicks"] = shortest
        for a, b in gaps:
            if b - a < min_gap:
                e.counterexample = True
                e.note(ep, a, b, f"two {op['event']} events {b - a} ticks apart (min {min_gap})")
    if e.triggered < 2:
        e.triggered = 0  # one event is not a pair: nothing to check


def _max_episode_rise(e: _Eval, ep: dict, op: dict) -> None:
    _samples, e.complete = _window(e.spec, ep)
    spans, recorded = signals.airborne_episodes(ep)
    if not recorded:
        e.applicable = "unknown"
        e.diagnostics.append("the trace has no floor state")
        return
    lo, hi = (_samples[0]["tick"], _samples[-1]["tick"]) if _samples else (0, -1)
    spans = [sp for sp in spans if lo <= sp["start"] <= hi]
    e.triggered = e.evaluated = len(spans)
    worst = max((sp["maxRise"] for sp in spans), default=0.0)
    e.metrics.update(maxRisePx=round(worst, 2), boundPx=op["maxPx"])
    for sp in spans:
        if sp["maxRise"] > op["maxPx"]:
            e.counterexample = True
            e.note(ep, sp["start"], sp["maxRiseTick"],
                   f"rose {sp['maxRise']:.0f} px above the floor it left (max {op['maxPx']:.0f})")


def _direction_agreement(e: _Eval, ep: dict, op: dict) -> None:
    samples, e.complete = _window(e.spec, ep)
    if not ep["capabilities"]["facing"]:
        e.applicable = "unknown"
        e.diagnostics.append("the trace has no facing record")
        return
    tps = ep["physicsTicksPerSecond"]
    mismatches = 0
    if op["subject"] == "actor":
        floor = op.get("minSpeedPxPerSec", 60.0)
        grace = op.get("graceTicks", 6)
        players = [s for s in samples if s["player"] is not None]
        last_dir, grace_until = None, -1
        for a, b in zip(players, players[1:]):
            dx = b["player"][0] - a["player"][0]
            if abs(dx) * tps < floor or b["facing"] is None:
                continue
            e.triggered += 1
            direction = 1 if dx > 0 else -1
            if direction != last_dir:
                last_dir, grace_until = direction, b["tick"] + grace - 1  # graceTicks ticks, this one included
            if b["tick"] <= grace_until:
                e.excluded += 1
                continue
            e.evaluated += 1
            if b["facing"] != direction:
                mismatches += 1
                if mismatches <= 3:
                    e.note(ep, a["tick"], b["tick"], f"moving {'right' if direction > 0 else 'left'} while facing "
                           f"{'right' if b['facing'] > 0 else 'left'}")
    else:
        if _cap(ep, "projectile") == "unknown":
            e.applicable = "unknown"
        horizon = op.get("horizonTicks", 6)
        min_travel = op.get("minTravelPx", 3.0)
        facing_at = {s["tick"]: s["facing"] for s in ep["samples"] if s["facing"] is not None}
        tracks: dict[int, list[tuple[int, float]]] = {}
        for s in ep["samples"]:
            for pid, x, _y in s["projectiles"] or []:
                tracks.setdefault(pid, []).append((s["tick"], x))
        lo, hi = samples[0]["tick"], samples[-1]["tick"]
        for pid, track in sorted(tracks.items()):
            t0, x0 = track[0]
            if not lo <= t0 <= hi:
                continue
            e.triggered += 1
            ahead = [p for p in track if p[0] <= t0 + horizon]
            facing = facing_at.get(t0, facing_at.get(t0 - 1))
            travel = ahead[-1][1] - x0
            if facing is None or ahead[-1][0] < t0 + horizon or abs(travel) < min_travel:
                e.excluded += 1  # gone before the horizon, or too slow to judge: never a pass by default
                continue
            e.evaluated += 1
            if (1 if travel > 0 else -1) != facing:
                mismatches += 1
                e.note(ep, t0, t0 + horizon, f"bullet {pid} travelled {travel:+.0f} px while the shooter faced "
                       f"{'right' if facing > 0 else 'left'}")
    e.metrics.update(mismatches=mismatches, maxMismatchCount=op["maxMismatchCount"])
    if mismatches > op["maxMismatchCount"]:
        e.counterexample = True


def _max_entity_drop(e: _Eval, ep: dict, op: dict) -> None:
    samples, e.complete = _window(e.spec, ep)
    cap = _cap(ep, e.spec["scope"]["class"])
    if cap == "unknown":
        e.applicable = "unknown"
    lo, hi = samples[0]["tick"], samples[-1]["tick"]
    tracks = signals.enemy_tracks(ep) or {}
    if not tracks and cap == "absent":
        e.applicable = "no"
        return
    worst = 0.0
    for eid, track in sorted(tracks.items()):
        track = [p for p in track if lo <= p[0] <= hi]
        if not track:
            continue
        e.triggered += 1
        settled = [p for p in track if p[0] >= track[0][0] + op["settleTicks"]]
        if not settled:
            e.excluded += 1
            continue
        e.evaluated += 1
        anchor = settled[0][2]
        low = max(settled, key=lambda p: p[2])
        drop = low[2] - anchor
        worst = max(worst, drop)
        if drop > op["maxDropPx"]:
            e.counterexample = True
            e.note(ep, settled[0][0], low[0], f"enemy {eid} dropped {drop:.0f} px below where it settled "
                   f"(max {op['maxDropPx']:.0f})")
    e.metrics.update(maxDropPx=round(worst, 2), boundPx=op["maxDropPx"])


def _event_response(e: _Eval, ep: dict, op: dict) -> None:
    samples, e.complete = _window(e.spec, ep)
    if _cap(ep, "projectile") == "unknown":
        e.applicable = "unknown"
    tps = ep["physicsTicksPerSecond"]
    lo, last = samples[0]["tick"], ep["completeness"]["lastTick"]
    hi = samples[-1]["tick"]
    deadline = _ticks(op["withinSeconds"], tps, bound="max")
    refractory = _ticks(op["refractorySeconds"], tps, bound="min")
    trig = op["trigger"]
    presses = sorted(i["tick"] for i in ep["inputs"]
                     if i["action"] == trig["action"] and i["pressed"] == trig["pressed"] and lo <= i["tick"] <= hi)
    responses = sorted(ev["tick"] for ev in ep["events"] if ev["type"] == op["response"])
    used: set[int] = set()
    unmatched = truncated = 0
    for t in presses:
        if any(t - refractory <= r < t for r in responses):
            e.excluded += 1  # not ready: a response just happened, so none is owed
            continue
        e.triggered += 1
        match = next((r for r in responses if t <= r <= t + deadline and r not in used), None)
        if match is not None:
            used.add(match)
            e.evaluated += 1
            continue
        if t + deadline > last:
            truncated += 1
            continue
        e.evaluated += 1
        unmatched += 1
        e.counterexample = True
        e.note(ep, t, t + deadline, f"{trig['action']} pressed when ready and no {op['response']} within "
               f"{deadline} ticks")
    e.metrics.update(unmatched=unmatched, truncated=truncated, deadlineTicks=deadline)
    if truncated and not e.counterexample:
        e.complete = False


def _min_event_count(e: _Eval, ep: dict, op: dict) -> None:
    samples, e.complete = _window(e.spec, ep)
    if _cap(ep, "projectile") == "unknown":
        e.applicable = "unknown"
        return
    lo, hi = samples[0]["tick"], samples[-1]["tick"]
    count = sum(1 for ev in ep["events"] if ev["type"] == op["event"] and lo <= ev["tick"] <= hi)
    e.metrics.update(count=count, min=op["min"])
    if not e.complete:
        return
    e.triggered = e.evaluated = 1  # the completed probe window is the trigger
    if count < op["min"]:
        e.counterexample = True
        e.note(ep, lo, hi, f"{count} {op['event']} events in the window (needs {op['min']})")


def _min_motion_extent(e: _Eval, ep: dict, op: dict) -> None:
    samples, e.complete = _window(e.spec, ep)
    if _cap(ep, e.spec["scope"]["class"]) == "unknown":
        e.applicable = "unknown"
    lo, hi = samples[0]["tick"], samples[-1]["tick"]
    window_ticks = {s["tick"] for s in samples}
    tracks = signals.enemy_tracks(ep) or {}
    smallest = None
    for eid, track in sorted(tracks.items()):
        track = [p for p in track if lo <= p[0] <= hi]
        if not track:
            continue
        e.triggered += 1
        if {p[0] for p in track} != window_ticks:
            e.excluded += 1  # not observed for the whole window: its extent is not established
            continue
        e.evaluated += 1
        extent = max(p[1] for p in track) - min(p[1] for p in track)
        smallest = extent if smallest is None else min(smallest, extent)
        if extent < op["minPx"]:
            e.counterexample = True
            e.note(ep, lo, hi, f"enemy {eid} moved {extent:.0f} px sideways (needs {op['minPx']:.0f})")
    e.metrics.update(minExtentPx=round(smallest, 2) if smallest is not None else None, boundPx=op["minPx"])


def _entity_present(e: _Eval, ep: dict, op: dict) -> None:
    samples, e.complete = _window(e.spec, ep)
    cap = _cap(ep, e.spec["scope"]["class"])
    if cap == "unknown":
        e.applicable = "unknown"
        return
    first = samples[0]["enemies"] or []
    ids = [eid for eid, _x, _y in first]
    e.triggered = len(ids)
    for eid in ids:
        e.evaluated += 1
        gone = next((s for s in samples if eid not in {p[0] for p in s["enemies"] or []}), None)
        if gone is not None:
            e.counterexample = True
            e.note(ep, samples[0]["tick"], gone["tick"], f"enemy {eid} is gone at tick {gone['tick']}")
    e.metrics.update(instances=len(ids))


COMPARATORS = {
    "lte": lambda r, l, tol: r <= l + tol,
    "gte": lambda r, l, tol: r >= l - tol,
    "lt": lambda r, l, tol: r + tol < l,
    "gt": lambda r, l, tol: r > l + tol,
    "eq": lambda r, l, tol: abs(r - l) <= tol,
}


def _relation(e: _Eval, left: dict, right: dict, op: dict) -> None:
    fn = signals.SIGNALS[op["signal"]]
    lv, rv = fn(left), fn(right)
    e.metrics.update(left=lv, right=rv, toleranceAbs=op["toleranceAbs"])
    _l, lc = _window(e.spec, left)
    _r, rc = _window(e.spec, right)
    e.complete = lc and rc
    if lv is None or rv is None:
        e.applicable = "unknown"
        e.diagnostics.append(f"{op['signal']} is undefined on {'the left' if lv is None else 'the right'} probe")
        return
    e.triggered = e.evaluated = 1
    if not COMPARATORS[op["comparator"]](rv, lv, op["toleranceAbs"]):
        e.counterexample = True
        e.note(right, right["completeness"]["firstTick"], right["completeness"]["lastTick"],
               f"{op['signal']} is {rv} on {right['id']} and {lv} on {left['id']}; expected right "
               f"{op['comparator']} left within {op['toleranceAbs']}")


OPERATORS = {
    "min_event_interval": _min_event_interval,
    "max_episode_rise": _max_episode_rise,
    "direction_agreement": _direction_agreement,
    "max_entity_drop": _max_entity_drop,
    "event_response": _event_response,
    "min_event_count": _min_event_count,
    "min_motion_extent": _min_motion_extent,
    "entity_present": _entity_present,
}


def evaluate(spec: dict, episode: dict, twin: dict | None = None) -> dict:
    """One spec on one episode, or a relation on (episode, twin): the left probe and the right one."""
    validate_v1(spec, "trace-spec")
    op = spec["operation"]
    episodes = [episode] if op["type"] != "relation" else [episode, twin]
    e = _Eval(spec, [ep for ep in episodes if ep is not None])
    try:
        if op["type"] == "relation":
            if twin is None:
                e.diagnostics.append("a relation needs two episodes")
                return e.verdict("execution_error")
            _relation(e, episode, twin, op)
        else:
            if e.spec["scope"]["class"] == "player" and not episode["capabilities"]["player"]:
                e.applicable = "unknown"
                return e.verdict()
            OPERATORS[op["type"]](e, episode, op)
    except Exception as exc:  # noqa: BLE001 - an evaluation that crashed is an error, never a result
        e.diagnostics.append(f"{type(exc).__name__}: {exc}"[:300])
        e.diagnostics.append(traceback.format_exc(limit=2)[-300:])
        return e.verdict("execution_error")
    verdict = e.verdict()
    validate_v1(verdict, "trace-verdict")
    return verdict
