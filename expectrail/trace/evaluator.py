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
presses, faster taps, the mirrored direction). It takes its bound from the game's own behaviour
on the twin probe, so it needs no number
from a person or a healthy reference build. ``signal_compare`` compares two signals in one observed
window, for example a reported UI counter against the collected coins. Undefined readings cannot pass.

``metamorphic`` (#675, piece 3) states a relation that holds on any game whose rules do not depend on
the direction: the twin probe is the left probe with each left/right action swapped (``mirror_x``),
and the player's sideways travel negates while its height, airborne time and air jumps stay equal.
A level is not symmetric, so the relation is judged only over the **clear window**: from the first
mirrored input to the tick before either twin touches something the trace shows is not mirrored with
it (``_mirror_contact``). The trace records no level geometry, so a contact is read from motion the
inputs and gravity do not explain. An episode with too short a clear window is not exercised; it is
never a pass.
"""
from __future__ import annotations

import math
import traceback

from expectrail.contracts import digest_v1, validate_v1
from expectrail.coverage import evidence_result
from expectrail.trace import signals

EVALUATOR = {"name": "expectrail.trace.evaluator", "version": "1.2.0"}
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

        mapping = episodes[0].get("frameMapping") if episodes else None
        # Trace-only episodes have no visual clock. A historical step is not a draw witness.
        self.draw_ticks = set(mapping.get("ticks", ())) if mapping is not None else None
        self.missing_draws = set()

    def observed(self, tick: int) -> bool:
        if self.draw_ticks is None or tick in self.draw_ticks:
            return True
        if tick not in self.missing_draws:
            self.diagnostics.append(f"needs-review: no captured frame at required event tick {tick}")
            self.missing_draws.add(tick)
        self.complete = False
        return False

    def note(self, ep: dict, a: int, b: int, detail: str) -> None:
        if len(self.evidence) < 8:
            self.evidence.append({"episodeId": ep["id"], "fromTick": int(a), "toTick": int(b), "detail": detail})

    def verdict(self, result: str | None = None) -> dict:
        req = self.spec["evidenceRequirement"]
        if result is None and self.missing_draws and not self.counterexample:
            result = "insufficient_observation"
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
    for a, b in zip(ticks, ticks[1:]):
        if not e.observed(a) or not e.observed(b):
            e.excluded += 1
            continue
        e.evaluated += 1
        gap = b - a
        e.metrics["shortestGapTicks"] = min(e.metrics.get("shortestGapTicks", gap), gap)
        if gap < min_gap:
            e.counterexample = True
            e.note(ep, a, b, f"two {op['event']} events {gap} ticks apart (min {min_gap})")
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
    e.triggered = len(spans)
    observed_spans = [sp for sp in spans if e.observed(sp["start"]) and e.observed(sp["maxRiseTick"])]
    e.evaluated = len(observed_spans)
    e.excluded = len(spans) - e.evaluated
    worst = max((sp["maxRise"] for sp in observed_spans), default=0.0)
    e.metrics.update(maxRisePx=round(worst, 2), boundPx=op["maxPx"])
    for sp in observed_spans:
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
            if not e.observed(t0):
                e.excluded += 1
                continue
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
                     if i.get("action") == trig["action"] and i["pressed"] == trig["pressed"] and lo <= i["tick"] <= hi)
    responses = sorted(ev["tick"] for ev in ep["events"] if ev["type"] == op["response"])
    used: set[int] = set()
    unmatched = truncated = 0
    for t in presses:
        recent = next((r for r in reversed(responses) if t - refractory <= r < t), None)
        if recent is not None:
            e.observed(recent)
            e.excluded += 1  # not ready: a response just happened, so none is owed
            continue
        e.triggered += 1
        match = next((r for r in responses if t <= r <= t + deadline and r not in used), None)
        trigger_drawn = e.observed(t)
        if match is not None:
            used.add(match)
            response_drawn = e.observed(match)
            if not (trigger_drawn and response_drawn):
                e.excluded += 1
                continue
            e.evaluated += 1
            continue
        if not trigger_drawn:
            e.excluded += 1
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
    ticks = [ev["tick"] for ev in ep["events"] if ev["type"] == op["event"] and lo <= ev["tick"] <= hi]
    count = len(ticks)
    e.excluded = sum(not e.observed(t) for t in ticks)
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


def _signal_compare(e: _Eval, ep: dict, op: dict) -> None:
    """Compare two measurements of the same observed window, without a guessed numeric bound."""
    samples, e.complete = _window(e.spec, ep)
    if not samples:
        return
    lo, hi = samples[0]["tick"], samples[-1]["tick"]
    window = {**ep, "samples": samples,
              "events": [v for v in ep["events"] if lo <= v["tick"] <= hi]}
    left = signals.SIGNALS[op["leftSignal"]](window)
    right = signals.SIGNALS[op["rightSignal"]](window)
    e.metrics.update(left=left, right=right, toleranceAbs=op["toleranceAbs"])
    if left is None or right is None:
        e.applicable = "unknown"
        e.diagnostics.append("signal_compare needs both signal readings in the observed window")
        return
    e.triggered = e.evaluated = 1
    if not COMPARATORS[op["comparator"]](right, left, op["toleranceAbs"]):
        e.counterexample = True
        e.note(ep, lo, hi, f"{op['rightSignal']} is {right}; expected {op['comparator']} "
               f"{op['leftSignal']} ({left}) within {op['toleranceAbs']}")


# --- metamorphic: mirror the inputs ---------------------------------------------------------------

# Fixed here, never in a spec, so a proposer cannot widen them. Measured on the bundled game (Godot
# 4.7.2, docs/measurements/675-metamorphic-mirror.md): gravity changes the fall by 0.146 px a tick, a
# walk speeds up and slows down by 0.125 px a tick, a wall stops it within one tick (by 0.85 px a tick
# at the slowest wall stop measured), and standing still moves the player by under 0.1 px. Sideways
# speed is explained only by a change of a paired (left/right) action: a jump press does not change
# it on the bundled game, so a wall met just after a jump press is still seen.
MIRROR = {
    "enemyClearPx": 48.0,       # an enemy this close may touch the player in one twin and not the other
    "horizontalJoltPx": 0.5,    # a change of sideways speed in one tick that no left/right input explains
    "verticalJoltPx": 0.5,      # a departure from gravity in one airborne tick that no input explains
    "groundDriftPx": 0.3,       # vertical motion in one tick while standing: moving or sloped ground
    "landingPx": 2.0,           # landing this far from the height it left: different ground
    "inputGraceTicks": 2,       # a change within this many ticks of an input change is the input's doing
    "minMotionPx": 8.0,         # sideways travel in the clear window, in either twin, before it says anything
}
MIRROR_SIGNALS = {"player_dx_px": "negate", "max_rise_px": "equal", "airborne_ticks": "equal", "air_jumps": "equal"}


def _mirrored_inputs(left: dict, right: dict, pairs: list[list[str]]) -> str | None:
    """None when ``right``'s inputs are ``left``'s with each paired action swapped; otherwise why not."""
    swap = {}
    for a, b in pairs:
        swap[a], swap[b] = b, a
    key = lambda i: (i["tick"], swap.get(i.get("action"), i.get("action")), i.get("pressed"), str(i.get("pointer")))  # noqa: E731
    if any("pointer" in i for i in left["inputs"] + right["inputs"]):
        return "a pointer input has no mirror the trace can check"
    want = sorted(key(i) for i in left["inputs"])
    have = sorted((i["tick"], i.get("action"), i.get("pressed"), str(i.get("pointer"))) for i in right["inputs"])
    if want != have:
        return "the twin's inputs are not the left probe's inputs mirrored"
    if not any(i.get("action") in swap for i in left["inputs"]):
        return "neither probe uses a paired action, so the mirror changes nothing"
    return None


def _mirror_contact(ep: dict, start: int, paired: set) -> tuple[int | None, str]:
    """The first tick at or after ``start`` where the player touches something, read from its motion."""
    m = MIRROR
    pts = {s["tick"]: s for s in signals.player_samples(ep)}
    changes = sorted({i["tick"] for i in ep["inputs"]})
    sideways = sorted({i["tick"] for i in ep["inputs"] if i.get("action") in paired})
    near = lambda t, ticks: any(t - m["inputGraceTicks"] <= c <= t for c in ticks)  # noqa: E731
    explained = lambda t: near(t, changes)  # noqa: E731
    airborne = []
    for t in sorted(pts):
        if all(u in pts and pts[u]["onFloor"] is False for u in (t, t - 1, t - 2)) and not explained(t):
            y0, y1, y2 = (pts[u]["player"][1] for u in (t - 2, t - 1, t))
            airborne.append((y2 - y1) - (y1 - y0))
    gravity = sorted(airborne)[len(airborne) // 2] if airborne else None
    anchor = None
    for t in sorted(pts):
        s = pts[t]
        if s["onFloor"] and pts.get(t - 1, {}).get("onFloor") is not False:
            anchor = s["player"][1]
        if t < start:
            continue
        x, y = s["player"]
        for eid, ex, ey in s.get("enemies") or []:
            if math.hypot(ex - x, ey - y) < m["enemyClearPx"]:
                return t, f"enemy {eid} is within {m['enemyClearPx']:.0f} px of the player"
        a, b = pts.get(t - 1), pts.get(t - 2)
        if a is None:
            continue
        on, was = s["onFloor"], a["onFloor"]
        if on is None or was is None:
            return t, "the floor state is not recorded"
        dy = y - a["player"][1]
        if on and was and abs(dy) > m["groundDriftPx"]:
            return t, "the ground under the player moved or sloped"
        if on and not was and anchor is not None and abs(y - anchor) > m["landingPx"]:
            return t, f"the player landed {anchor - y:+.0f} px from the height it left"
        if not on and was and not explained(t):
            return t, "the player left the ground with no input (a ledge or a push)"
        if b is None:
            continue
        ddx = (x - a["player"][0]) - (a["player"][0] - b["player"][0])
        if abs(ddx) > m["horizontalJoltPx"] and not near(t, sideways):
            return t, "the player's sideways speed changed with no change of input (a wall or another body)"
        if gravity is not None and not on and not was and b["onFloor"] is False and not explained(t):
            ddy = dy - (a["player"][1] - b["player"][1])
            if abs(ddy - gravity) > m["verticalJoltPx"]:
                return t, "the player's fall departed from gravity with no input (a ceiling or a spring)"
    return None, ""


def _clear(ep: dict, first: int, last: int) -> dict:
    """The episode cut to the clear window: what happened before the first mirrored input is the same on
    both twins, so a signal read there (the player settling on the floor) is no evidence either way."""
    inside = lambda t: first <= t <= last  # noqa: E731
    return {**ep, "samples": [s for s in ep["samples"] if inside(s["tick"])],
            "events": [v for v in ep["events"] if inside(v["tick"])],
            "inputs": [i for i in ep["inputs"] if inside(i["tick"])],
            "completeness": {**ep["completeness"], "firstTick": max(first, ep["completeness"]["firstTick"]),
                             "lastTick": min(last, ep["completeness"]["lastTick"])}}


def _metamorphic(e: _Eval, left: dict, right: dict, op: dict) -> None:
    signal, relation = op["signal"], op["relation"]
    if MIRROR_SIGNALS.get(signal) != relation:
        raise ValueError(f"{signal} does not {relation} under {op['transform']}")
    why = _mirrored_inputs(left, right, op["pairs"])
    if why is not None:
        e.applicable = "unknown"
        e.diagnostics.append(f"cannot tell: {why}")
        return
    for ep in (left, right):
        if not (ep["capabilities"]["player"] and ep["capabilities"]["onFloor"]):
            e.applicable = "unknown"
            e.diagnostics.append(f"cannot tell: {ep['id']} has no player position or floor state, so no contact "
                                 "can be seen")
            return
    paired = {a for pair in op["pairs"] for a in pair}
    ls, lc = _window(e.spec, left)
    rs, rc = _window(e.spec, right)
    e.complete = lc and rc
    if not ls or not rs:
        return
    lo, hi = max(ls[0]["tick"], rs[0]["tick"]), min(ls[-1]["tick"], rs[-1]["tick"])
    start = min((i["tick"] for i in left["inputs"] if i.get("action") in paired and lo <= i["tick"] <= hi), default=None)
    e.metrics.update(left=None, right=None, toleranceAbs=op["toleranceAbs"], clearFromTick=start, clearToTick=None)
    if start is None:
        e.diagnostics.append("no mirrored input inside the window")
        return
    contacts = [(t, side, why) for side, ep in (("left", left), ("right", right))
                for t, why in [_mirror_contact(ep, start, paired)] if t is not None]
    end = hi
    if contacts:
        t, side, why = min(contacts)
        end = min(hi, t - 1)
        e.diagnostics.append(f"clear window ends at tick {end}: on the {side} probe at tick {t}, {why}")
    e.metrics["clearToTick"] = end
    if end <= start:
        e.diagnostics.append("not exercised: the clear window holds no tick after the first mirrored input")
        return
    lw, rw = _clear(left, start, end), _clear(right, start, end)
    for ep in (lw, rw):
        if any(not (g[1] < start or g[0] > end) for g in ep["completeness"]["gaps"]):
            e.complete = False
    xs = [{s["tick"]: s["player"][0] for s in signals.player_samples(ep)} for ep in (lw, rw)]
    moved = max((max(x.values()) - min(x.values()) for x in xs if x), default=0.0)
    fn = signals.SIGNALS[signal]
    lv, rv = fn(lw), fn(rw)
    e.metrics.update(left=lv, right=rv, movedPx=round(moved, 2))
    if lv is None or rv is None:
        e.applicable = "unknown"
        e.diagnostics.append(f"{signal} is undefined on {'the left' if lv is None else 'the right'} probe")
        return
    if moved < MIRROR["minMotionPx"]:
        e.diagnostics.append(f"not exercised: the player moved {moved:.1f} px sideways in the clear window "
                             f"(needs {MIRROR['minMotionPx']:.0f})")
        return
    if relation == "equal" and not lv and not rv:
        e.diagnostics.append(f"not exercised: {signal} is 0 on both probes in the clear window")
        return
    e.triggered = e.evaluated = 1
    ok = abs(rv + lv) <= op["toleranceAbs"] if relation == "negate" else abs(rv - lv) <= op["toleranceAbs"]
    if not ok:
        e.counterexample = True
        e.note(right, start, end, f"{signal} is {rv} on {right['id']} and {lv} on {left['id']} from tick {start} "
               f"to {end}; mirrored, it should {relation} within {op['toleranceAbs']}")


OPERATORS = {
    "signal_compare": _signal_compare,
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
    paired = op["type"] in ("relation", "metamorphic")
    episodes = [episode] if not paired else [episode, twin]
    e = _Eval(spec, [ep for ep in episodes if ep is not None])
    try:
        for ep in e.episodes:
            problem = ep["completeness"].get("captureProblem")
            mapping = ep.get("frameMapping") or {}
            window = spec["window"]
            if not problem and mapping.get("protocol") == "capture-ticks/v1" and window["kind"] == "ticks":
                lo, hi = window["fromTick"], window["toTick"]
                if not any(lo <= tick <= hi for tick in mapping["ticks"]):
                    problem = f"no captured frame in required window (ticks {lo} to {hi})"
            if problem:
                e.complete = False
                e.diagnostics.append(f"needs-review: {problem}")
                return e.verdict("insufficient_observation")
        if paired:
            if twin is None:
                e.diagnostics.append(f"a {op['type']} needs two episodes")
                return e.verdict("execution_error")
            (_relation if op["type"] == "relation" else _metamorphic)(e, episode, twin, op)
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
