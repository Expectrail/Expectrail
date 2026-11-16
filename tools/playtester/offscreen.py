"""One generic observation: the recorded player body stays outside the game view.

Only a trace and independently supplied viewport dimensions are read. No report prose, defect
identity, game-specific mechanics or expected behavior parameters enter this observation.
"""
from __future__ import annotations

import math

from .producer import OFFSCREEN, point


def viewport_size(value) -> tuple[float, float]:
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in value)):
        raise ValueError("viewport must contain two positive finite dimensions")
    return tuple(value)


def outside(row: dict, viewport: tuple[float, float]) -> bool | None:
    """None means unknown. Transform all body corners, including rotated/mirrored views."""
    body, view = row.get("body"), row.get("view")
    if row.get("playerVisible") is not True or point(row) is None:
        return None
    if (not isinstance(body, list) or len(body) != 4 or not isinstance(view, list) or len(view) != 6
            or any(type(n) not in (int, float) or not math.isfinite(n) for n in body + view)):
        return None
    left, top, right, bottom = body
    if left > right or top > bottom or view[0] * view[3] - view[1] * view[2] == 0:
        return None
    xs, ys = [], []
    for x, y in ((left, top), (right, top), (left, bottom), (right, bottom)):
        xs.append(view[0] * x + view[2] * y + view[4])
        ys.append(view[1] * x + view[3] * y + view[5])
    if any(not math.isfinite(n) for n in xs + ys):
        return None
    # Touching an edge still counts as potentially visible. No origin-only clipping guess.
    return max(xs) < 0 or min(xs) > viewport[0] or max(ys) < 0 or min(ys) > viewport[1]


def findings(trace: dict, viewport) -> list[dict]:
    viewport = viewport_size(viewport)
    rate = trace.get("physicsTicksPerSecond")
    if type(rate) is not int or rate <= 0:
        raise ValueError("offscreen observation requires a positive physics tick rate")
    consecutive = 0
    rows = trace["rows"]
    for tick, row in enumerate(rows):
        consecutive = consecutive + 1 if outside(row, viewport) is True else 0
        if consecutive >= rate and tick and point(rows[tick - 1]) is not None:
            before = point(rows[tick - 1])
            return [{"bug": OFFSCREEN, "fault": {"preFaultTick": tick - 1, "faultTick": tick,
                     "anchor": {"object": "Player", "x": before[0], "y": before[1], "tolerancePx": 2}}}]
    return []
