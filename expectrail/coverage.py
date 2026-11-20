"""Shared evidence sufficiency semantics, originally expectrail.trace.evaluator._Eval.verdict.

A concrete counterexample still fails. An obligation that never fires or lacks enough evaluations
is not_exercised, never a pass. Unknown applicability or an incomplete required window needs data.
This module is standard library only so both the installed gate and trace interpreter can use it.
"""
from __future__ import annotations

import math
from fractions import Fraction


def all_of(runs: list[str], outcome: str, reps: int = 3) -> bool:
    """The shared repetition predicate, originally jit.assess.all_of."""
    return len(runs) >= reps and all(r == outcome for r in runs[:reps])


def evidence_result(*, counterexample: bool, applicable: str, triggered: int, evaluated: int,
                    minimum_triggers: int, minimum_evaluations: int, complete: bool,
                    complete_window: bool) -> str:
    if counterexample:
        return "fail"
    if applicable == "unknown":
        return "insufficient_observation"
    if applicable == "no" or triggered == 0 or triggered < minimum_triggers or evaluated < minimum_evaluations:
        return "not_exercised"
    if complete_window and not complete:
        return "insufficient_observation"
    return "pass"


def _finite_number(value) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _role_drawing(row: dict, role: str):
    objects = row.get('roleObjects')
    if not isinstance(objects, list) or not all(isinstance(o, dict) and isinstance(o.get('role'), str) for o in objects):
        return None
    matches = [obj for obj in objects if obj.get('role') == role]
    if len(matches) != 1:
        return None
    obj = matches[0]
    identity = obj.get('id')
    if not isinstance(identity, str) or not identity.strip():
        return None
    if obj.get('boundsSource') != 'drawing' or obj.get('visible') is not True:
        return None
    box = obj.get('worldBox')
    if not isinstance(box, list) or len(box) != 4 or not all(_finite_number(v) for v in box):
        return None
    x0, y0, x1, y1 = box
    if x0 >= x1 or y0 >= y1:
        return None
    return identity, box


def _pixels(value: int | float) -> int | Fraction:
    # The recorder writes decimal pixel coordinates. Compare rectangle extents and
    # inclusive thresholds in those units without float overflow or round-off.
    return Fraction(str(value)) if type(value) is float else value


def _role_displacement(condition: dict, trace: dict | None) -> int | Fraction | None:
    role, axis = condition.get('role'), condition.get('axis')
    start, end = condition.get('fromTick'), condition.get('toTick')
    minimum = condition.get('minIncreasePx')
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        return None
    if axis not in ('x', 'y') or not _finite_number(minimum) or minimum <= 0:
        return None
    if not isinstance(trace, dict) or not isinstance(role, str) or not role:
        return None
    bindings = trace.get('bindings')
    capabilities = trace.get('capabilities')
    if not isinstance(capabilities, dict) or capabilities.get('roleBoxes') is not True:
        return None
    binding = bindings.get(role) if isinstance(bindings, dict) else None
    if not isinstance(binding, dict) or ('node' in binding) == ('group' in binding):
        return None
    selector = binding.get('node', binding.get('group'))
    if not isinstance(selector, str) or not selector:
        return None
    rows = trace.get('rows')
    if not isinstance(rows, list) or not all(isinstance(r, dict) and type(r.get('tick')) is int for r in rows):
        return None
    interval = [r for r in rows if start <= r['tick'] <= end]
    if len(interval) != end - start + 1:
        return None
    samples = []
    for tick, row in enumerate(interval, start):
        sample = _role_drawing(row, role)
        if row['tick'] != tick or sample is None or (samples and sample[0] != samples[0][0]):
            return None
        samples.append(sample)
    before, after = samples[0][1], samples[-1][1]
    # Both edges of each axis must translate together: a changing rectangle
    # could move its midpoint without the object moving at all.
    left, top, right, bottom = (_pixels(b) - _pixels(a) for a, b in zip(before, after))
    if left != right or top != bottom:
        return None
    return left if axis == 'x' else top


def checkpoint(condition: dict, trace: dict | None, *, notes: list[str] | None = None) -> bool | None:
    """True: reached, False: observed but not reached, None: required data was unavailable.

    These are route checkpoints from the engine, independent of who judges the visual assertion.
    No missing position, floor flag or coin list is invented. An explicit empty coin list is zero.
    """
    if condition['type'] == 'role-displacement':
        delta = _role_displacement(condition, trace)
        if delta is None:
            if notes is not None:
                notes.append(f"check the visible {condition.get('role')} drawing at each tick from "
                             f"{condition.get('fromTick')} to {condition.get('toTick')} for one comparable instance")
            return None
        minimum = condition['minIncreasePx']
        reached = delta >= _pixels(minimum)
        if not reached and notes is not None:
            direction = 'down' if condition['axis'] == 'y' else 'right'
            start, end = condition['fromTick'], condition['toTick']
            # Preserve the comparison when a rounded display value could equal the threshold.
            amount = str(delta) if delta.denominator == 1 else f"less than {minimum}"
            notes.append(f"{condition['role']} moved {amount} world pixels {direction} between ticks "
                         f"{start} and {end} (requires {minimum})")
        return reached
    if condition['type'] == 'position-at-tick':
        rows = [r for r in (trace or {}).get('rows', []) if r.get('tick') == condition['tick']]
        if len(rows) != 1:
            return None
        row, name = rows[0], condition['object']
        point = row.get('player') if name == 'player' else None
        for prefix, field in [('enemy-', 'enemies'), ('projectile-', 'projectiles')]:
            if name.startswith(prefix) and name[len(prefix):].isdigit():
                tracked = row.get(field)
                matches = [p[1:] for p in (tracked if isinstance(tracked, list) else [])
                           if isinstance(p, list) and len(p) == 3 and str(p[0]) == name[len(prefix):]]
                point = matches[0] if len(matches) == 1 else None
        if not isinstance(point, list) or len(point) != 2 or any(
                type(v) not in (int, float) or not math.isfinite(v) for v in point):
            return None
        return math.hypot(point[0] - condition['x'], point[1] - condition['y']) <= condition['tolerancePx']
    rows = [r for r in (trace or {}).get("rows", []) if r.get("tick", -1) >= condition.get("fromTick", 0)]
    if not rows:
        return None
    kind = condition["type"]
    known, values = True, []
    for row in rows:
        if kind == "on-floor":
            value = row.get("onFloor")
            if type(value) is not bool or row.get("player") is None:
                known = False
                continue
            if value:
                return True
        elif kind == "position-region":
            point = row.get("player")
            if not isinstance(point, list) or len(point) != 2:
                known = False
                continue
            x0, y0, x1, y1 = condition["box"]
            if x0 > x1 or y0 > y1:
                raise ValueError("coverage position-region box is inverted")
            if x0 <= point[0] <= x1 and y0 <= point[1] <= y1:
                return True
        elif kind == "coin-count-change":
            coins = row.get("coins")
            if not isinstance(coins, list):
                known = False
                continue
            values.append(len(coins))
            if len(set(values)) > 1:
                return True
        else:
            raise ValueError(f"unknown coverage checkpoint: {kind}")
    return False if known else None


def assess(spec: dict, observations: dict, judged: int, *, counterexample: bool,
           route: str | None = None, trace: dict | None = None, expected_frames: list[int] | None = None) -> tuple[dict, str]:
    obligation = spec.get("coverage", {})
    window = spec.get("window", {})
    lo, hi = window.get("fromFrame", 0), window.get("toFrame")
    have = {f['frame'] for f in observations['frames'] if type(f.get('frame')) is int
            and f['frame'] >= lo and (hi is None or f['frame'] <= hi)}
    # A bounded spec names its own denominator. The gate supplies route-derived bounds otherwise.
    want = set(expected_frames) if expected_frames is not None else (set(range(lo, hi + 1)) if hi is not None else have)
    if hi is not None and hi < lo:
        raise ValueError("the coverage window ends before it starts")
    existential = spec['assertion']['type'] == 'reaches'
    one_frame = hi == lo or (hi is None and expected_frames is None and len(have) <= 1)
    default_minimum = 1 if existential or one_frame else 2
    minimum = max(obligation.get('minFrames', default_minimum),
                  math.ceil(obligation.get('minFraction', 0) * len(want)))
    applicable = 'yes'
    if 'routes' in obligation:
        applicable = 'unknown' if route is None else ('yes' if route in obligation['routes'] else 'no')
    notes = []
    checkpoints = [checkpoint(c, trace, notes=notes) for c in obligation.get('reached', [])] if applicable == 'yes' else []
    triggered = 0 if False in checkpoints else judged
    if None in checkpoints:
        applicable = 'unknown'
    complete = bool(want) and want <= have
    # reaches is existential: its witness is sufficient unless the spec adds stronger obligations.
    # The gate independently requires the complete route and captured window, for every assertion.
    semantic = evidence_result(counterexample=counterexample and applicable != 'no', applicable=applicable,
                               triggered=triggered, evaluated=judged, minimum_triggers=1,
                               minimum_evaluations=minimum, complete=complete, complete_window=expected_frames is not None and not existential)
    status = ('not-applicable' if applicable == 'no' else 'not-reached' if False in checkpoints
              else 'not-exercised' if semantic == 'not_exercised'
              else 'insufficient-observation' if semantic == 'insufficient_observation' else 'exercised')
    detail = (f"{judged} judged frames; needs {minimum}; observed {len(have & want)} of {len(want)} window frames")
    if status == 'not-reached':
        detail += '; checkpoint not-reached'
    elif None in checkpoints:
        detail += '; checkpoint data unavailable'
    elif applicable == 'unknown':
        detail += '; route applicability unknown'
    if notes:
        detail += '. ' + '. '.join(notes)
    return {'status': status, 'semanticResult': semantic, 'framesObserved': len(have & want),
            'framesExpected': len(want), 'framesRequired': minimum, 'completeWindow': complete}, detail
