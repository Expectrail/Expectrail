"""Shared evidence sufficiency semantics, originally expectrail.trace.evaluator._Eval.verdict.

A concrete counterexample still fails. An obligation that never fires or lacks enough evaluations
is not_exercised, never a pass. Unknown applicability or an incomplete required window needs data.
This module is standard library only so both the installed gate and trace interpreter can use it.
"""
from __future__ import annotations

import math


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


def checkpoint(condition: dict, trace: dict | None) -> bool | None:
    """True: reached, False: observed but not reached, None: required data was unavailable.

    These are route checkpoints from the engine, independent of who judges the visual assertion.
    No missing position, floor flag or coin list is invented. An explicit empty coin list is zero.
    """
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
    checkpoints = [checkpoint(c, trace) for c in obligation.get('reached', [])] if applicable == 'yes' else []
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
    return {'status': status, 'semanticResult': semantic, 'framesObserved': len(have & want),
            'framesExpected': len(want), 'framesRequired': minimum, 'completeWindow': complete}, detail
