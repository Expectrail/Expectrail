"""Measured configured Godot roles. Older configured traces remain readable, but unmeasured.

The recorder supplies drawing bounds (or an explicit collision fallback), never a bundled size.
Engine visibility is lifecycle evidence, not a claim about pixels, shaders, alpha or occlusion.
"""
from __future__ import annotations

from agents.observations import _frame_box, _logged_ground_point, _polygon_top
from expectrail import observation_timeline as timeline


def configured(trace: dict) -> bool:
    return bool(trace.get('bindings')) or trace.get('capabilities', {}).get('roleBoxes') is True


def rows_by_frame(trace: dict, frames, fps: int = 60, physics_tps=None):
    if trace.get('capabilities', {}).get('roleBoxes') is not True:
        return
    rows = trace.get('rows') or []
    for frame in frames:
        tick = timeline.tick_for(trace, frame, fps)
        if 0 <= tick < len(rows) and isinstance(rows[tick].get('roleObjects'), list):
            row = rows[tick]
            if 'captureTimeline' in trace:
                view = timeline.view_for(trace, frame, fps)
                row = {**row, 'roleObjects': [{**o, 'box': _frame_box(view, o['worldBox'])}
                                            for o in row['roleObjects']]}
            yield frame, tick, row


def refs(trace: dict, frames, fps=60) -> dict:
    # Include hidden/offscreen instances here: this is an engine placement filter, not vision.
    out = {}
    for frame, _, row in rows_by_frame(trace, frames, fps):
        roles = {role: [] for role in trace.get('bindings', {})}
        for obj in row['roleObjects']:
            if obj['role'] in roles:
                roles[obj['role']].append(list(obj['box']))
        out[frame] = roles
    return out


def _visible(obj: dict, size) -> bool:
    if obj.get('visible') is not True or not size:
        return False
    a, b, c, d = obj['box']
    return c > a and d > b and c > 0 and d > 0 and a < size[0] and b < size[1]


def ground(trace: dict, size, frames, fps=60) -> dict:
    out = {}
    rows = trace.get('rows') or []
    for frame, tick, row in rows_by_frame(trace, frames, fps):
        size = timeline.placement(trace, frame, fps)['viewport'] if 'captureTimeline' in trace else size
        if 'ground' in trace.get('bindings', {}) and not trace.get('groundReference'):
            boxes = [{'box': list(o['box']), 'score': 1.0, 'source': 'engine'}
                     for o in row['roleObjects'] if o['role'] == 'ground' and _visible(o, size)]
        else:
            point = _logged_ground_point(row, timeline.view_for(trace, frame, fps))
            boxes = [] if point is None or not size else [
                {'box': [0.0, round(point[1], 3), float(size[0]), float(max(size[1], point[1]+1))],
                 'score': 1.0, 'source': 'engine'}]
        out[frame] = {'ground': boxes}
    return out


def observations(trace: dict, replay_sha256: str, fps=60, physics_tps=None) -> dict:
    size = trace.get('viewport')
    rows = trace.get('rows') or []
    count = timeline.frame_count(trace, fps)
    frames = []
    tracks = {}
    ground_trace = {**trace, 'physicsTicksPerSecond': physics_tps} if physics_tps else trace
    ground_frames = ground(ground_trace, size, range(count), fps)
    for frame, _, row in rows_by_frame(trace, range(count), fps, physics_tps):
        size = timeline.placement(trace, frame, fps)['viewport'] if 'captureTimeline' in trace else size
        if not size:
            continue  # old configured trace: never make up a viewport or a box
        objects = {role: [] for role in trace.get('bindings', {})}
        for obj in row['roleObjects']:
            role = obj['role']
            if role not in objects or not _visible(obj, size):
                continue
            track = tracks.setdefault(obj['id'], len(tracks)+1)
            objects[role].append({'box': list(obj['box']), 'score': 1.0, 'track': track, 'source': 'engine',
                                  **({'entityId': str(obj['id'])} if 'captureTimeline' in trace else {})})
        objects['ground'] = ground_frames.get(frame, {'ground': []})['ground']
        frames.append({'frame': frame, 'objects': objects})
    document = {'format': 'expectrail.observations/v0', 'replay': {'sha256': replay_sha256},
            'model': {'name': 'expectrail.godot-roles', 'units': 'captured-frame pixels',
                      'ground': 'measured engine geometry; not pixel evidence'}, 'frames': frames}
    return timeline.emit(document, trace, version='godot-roles/1')


def reference_ground(trace: dict, surfaces: list) -> dict:
    """Trusted surfaces under the measured drawing's columns; no bundled feet/width/art offsets.

    Only a surface starting between the drawing's top and below its feet is a candidate. Missing
    geometry stays unmeasured. This does not calibrate the relationship between art and collision.
    """
    rows = []
    for original in trace.get('rows') or []:
        row = dict(original)
        players = [o for o in row.get('roleObjects', []) if o['role'] == 'player']
        best = None
        if len(players) == 1:
            left, top, right, _ = players[0]['worldBox']
            for x in (left, (left+right)/2, right):
                for polygon in surfaces:
                    y = _polygon_top(polygon, x)
                    if y is not None and y >= top and (best is None or y < best):
                        best = y
        row.pop('ground', None)
        if best is not None:
            row['ground'] = round(best, 3)
        rows.append(row)
    return {**trace, 'rows': rows, 'groundReference': 'clean level; measured role drawing columns'}
