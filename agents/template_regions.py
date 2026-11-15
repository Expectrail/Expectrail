"""Pixel-position crossing checks against regions frozen from trusted clean calibration.

This is a reference-map check, not segmentation of candidate ground. Only measured
pixel boxes and the harness camera are read from a candidate. Candidate body, ground
and surface claims never establish the reference boundary.
"""
from __future__ import annotations

import copy
import math

from agents import template_observations as sensor

TOLERANCE_PX = 20


def usable_view(view):
    return (isinstance(view, list) and len(view) == 6
            and all(type(v) in (int, float) and math.isfinite(v) for v in view)
            and view[0] > 0 and view[3] > 0 and view[1] == 0 and view[2] == 0)


def check(proof, reference, *, tolerance=TOLERANCE_PX):
    """Recompute above-to-below crossings; missing pixels/cameras remain unavailable.

    Regions start unarmed. A region is armed only after the measured player is above
    its top (within tolerance), so walking beneath an overhead platform is not itself
    a crossing. Horizontal overlap must remain applicable. This does not certify a
    spawn beneath terrain, a changed candidate floor, or gaps with no pixel evidence.
    """
    indices = [row['frame'] for row in proof]
    if indices != sorted(set(indices)):
        raise sensor.SensorError('region proof frames must be unique and increasing')
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance < 0:
        raise sensor.SensorError('invalid region crossing tolerance')
    regions = []
    for polygon in reference['polygons'] if reference else []:
        segments = []
        for a, b in zip(polygon, polygon[1:]+polygon[:1]):
            if a[0] != b[0]:
                segments.append((min(a[0], b[0]), max(a[0], b[0]), a[0], a[1], (b[1]-a[1])/(b[0]-a[0])))
        regions.append((min(p[0] for p in polygon), max(p[0] for p in polygon), segments))
    armed, crossed, unavailable = set(), [], []
    for row in proof:
        box, view = row['box'], row['view']
        if not regions or not sensor.finite_box(box) or not usable_view(view):
            unavailable.append(row['frame'])
            armed.clear()
            continue
        x0, x1 = (box[0]-view[4])/view[0], (box[2]-view[4])/view[0]
        bottom, margin = (box[3]-view[5])/view[3], tolerance/view[3]
        for index, (left, right, segments) in enumerate(regions):
            if x1 <= left or x0 >= right:
                armed.discard(index)
                continue
            x = (max(x0, left)+min(x1, right))/2
            intersections = [y+(x-start)*slope for lo, hi, start, y, slope in segments if lo <= x <= hi]
            if not intersections:
                continue
            top = min(intersections)
            if bottom <= top+margin:
                armed.add(index)
            elif index in armed:
                crossed.append(row['frame'])
                break
    return dict(tolerancePx=tolerance, proof=copy.deepcopy(proof), crossedFrames=crossed, unavailableFrames=unavailable)


def from_observations(doc, trace, reference):
    fps = doc['model']['sensor']['captureFps']
    tps = trace['physicsTicksPerSecond']
    if tps < fps or tps % fps:
        raise sensor.SensorError('region capture fps must divide physics ticks')
    rows = {row['tick']: row for row in trace['rows']}
    proof = []
    for frame in doc['frames']:
        tick = (frame['frame']+1)*(tps//fps)-1
        camera = rows.get(tick+1, rows.get(tick, {}) if tick == trace['ticks']-1 else {}).get('view')
        found = frame['objects'].get('player') or []
        proof.append(dict(frame=frame['frame'], box=found[0]['box'] if found else None,
                          view=camera if usable_view(camera) else None))
    return check(proof, reference)
