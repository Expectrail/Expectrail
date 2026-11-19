"""A no-model witness for a round sprite that rotates: the bundled game's bullet (#286). No model or network.

Why the bullet needs its own witness. Measured on the real engine (docs/new-work/2026-11-19-sensor-bullet.md):

- **It turns.** The bullet is a RigidBody2D: it spins as it flies and bounces, and its 16 x 16 art is drawn
  rotated, so its pixels change from frame to frame. Templates matched pixel for pixel
  (template_foreground.py) found it on about a third to two thirds of clean frames.
- **Its colours are not its art's.** A glow child (``Glow``, ``blend_mode = 1``, additive) is drawn over the
  sprite, so no rendered pixel is in the art's palette and the palette mask is empty.
- **It is drawn behind its logged box.** ``physics_interpolation`` is on in the game's project, and the bullet
  moves about 14 frame pixels a tick: each frame draws it between 1 and 1.7 ticks behind the box the trace
  logs for the frame's tick. The player and the enemy move a few pixels a tick, inside the sensor's search.
- **It fades out.** Its ``Timer`` (1 s, the default) calls ``destroy``, which fades the sprite over 0.3 s.

So the witness reads what does not change when the sprite turns: the mean colour of each one-pixel ring around
its centre (``profile``). The rings are measured on trusted clean replays only, where the approved art itself
locates the sprite (luminance correlation over the art's opaque footprint, ``locate``) on the path the engine
logged (``paths``). A frame's box is ``matched`` when some position on that path has rings within
``maxDistance`` (mean absolute RGB difference) of one of the frozen profiles, and ``not-found`` when none does.
The search never leaves the logged path, so a match is always where the engine puts the object.

What it says nothing about: which way the bullet faces, its exact pixels, a bullet partly on screen or touching
another object's box (a gap), and a bullet in its last ``fadesAfterTicks`` (a gap). Validation on a separate
clean replay decides ``met``, with the player's rule (template_foreground.py ``_object_calibration``).
"""
from __future__ import annotations

import hashlib
import json
import math

from agents import template_observations as sensor

ALGORITHM = 'expectrail.radial-witness/v1'
# The frame draws the object between its box ``PATH_TICKS`` ticks before the frame's tick and the box on it.
PATH_TICKS = 2
# The approved art must locate the sprite with at least this luminance correlation for a clean ring profile.
LOCATE_FLOOR = 0.85
# A position matches when its rings differ from a frozen profile by at most this, in mean absolute RGB (0-255).
# Fixed before validation, not chosen on it: on the clean probes measured on November 19 the clean bullet was
# within 3 at the 95th percentile, and nothing else on screen came within 33.
MAX_DISTANCE = 12.0
# Search this many pixels beyond the path's ends, for rounding.
PAD = 3
# A profile within this distance of one already kept adds nothing.
DUPLICATE = 1.0
MAX_PROFILES = 512


def numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise sensor.SensorError('the radial witness needs NumPy; no model is used') from exc
    return np


def rings_for(side: int) -> int:
    """The rings read for a sprite ``side`` pixels across: those wholly inside its drawn disc."""
    return max(2, side // 2 - 2)


def _ring_index(side: int):
    np = numpy()
    centre = (side - 1) / 2
    y, x = np.mgrid[0:side, 0:side]
    return np.hypot(x - centre, y - centre).astype(int)


def profile(rgb, rings: int):
    """The mean colour of each one-pixel ring around the centre of a square RGB crop, innermost first."""
    np = numpy()
    side = rgb.shape[0]
    if rgb.shape[:2] != (side, side) or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise sensor.SensorError('a ring profile is read from a square RGB crop')
    index = _ring_index(side)
    pixels = rgb.astype(np.float64)
    return np.concatenate([pixels[index == k].mean(0) for k in range(rings)])


def distance(a, b) -> float:
    np = numpy()
    return float(np.abs(np.asarray(a, np.float64) - np.asarray(b, np.float64)).mean())


def paths(trace, frames, role, fps=60, path_ticks=PATH_TICKS):
    """{frame: [(id, before, now, age), ...]} for every ``role`` object the engine logged on the frame's tick, or
    {frame: None} when the record cannot say. ``now`` is its box on the frame's tick and ``before`` its box
    ``path_ticks`` earlier (or the first logged after that, or ``now``), both through the camera
    template_observations.py ``object_predictions`` uses for the frame (the view logged on the next tick). ``age`` is ticks since it was first logged."""
    field = sensor.OBJECT_BOXES.get(role)
    if field is None:
        raise sensor.SensorError(f'the engine logs no box for {role!r}')
    tps = trace.get('physicsTicksPerSecond')
    if type(tps) is not int or type(fps) is not int or fps <= 0 or tps < fps or tps % fps:
        raise sensor.SensorError('capture fps must divide the recorded physics tick rate')
    if type(path_ticks) is not int or path_ticks < 0:
        raise sensor.SensorError('the path is a whole number of ticks')
    rows = trace.get('rows', [])
    by_tick = {r.get('tick'): r for r in rows}
    if len(by_tick) != len(rows):
        raise sensor.SensorError('duplicate trace ticks')
    logged = (trace.get('capabilities') or {}).get('objectBoxes') is True
    first = {}
    for r in sorted(rows, key=lambda r: r['tick']):
        for entry in r.get(field) or []:
            if isinstance(entry, list) and entry and type(entry[0]) is int:
                first.setdefault(entry[0], r['tick'])
    last_tick = trace.get('ticks', len(rows)) - 1

    def camera(tick):
        row = by_tick.get(tick)
        later = by_tick.get(tick + 1, row if tick == last_tick else None)
        return later.get('view') if later else None

    def boxes_at(tick, view):
        row = by_tick.get(tick)
        entries = row.get(field) if row else None
        if not isinstance(entries, list) or view is None:
            return None
        out = {}
        for entry in entries:
            if not (isinstance(entry, list) and len(entry) == 5 and type(entry[0]) is int):
                return None
            box = sensor._on_screen(entry[1:], view)
            if box is None:
                return None
            out[entry[0]] = box
        return out

    step = tps // fps
    out = {}
    for frame in frames:
        tick = (frame + 1) * step - 1
        # Every box of the frame through the frame's own camera: the body is drawn behind its logged box, the
        # camera is not (measured on the bundled game: a still bullet, the camera scrolling 14 pixels a tick).
        view = camera(tick)
        now = boxes_at(tick, view) if logged else None
        if now is None:
            out[frame] = None
            continue
        earlier = [boxes_at(tick - k, view) if tick - k >= 0 else None for k in range(path_ticks, 0, -1)]
        found = []
        for ident, box in sorted(now.items()):
            # Its box ``path_ticks`` back, or the first one logged after that (a bullet fired since).
            before = next((b[ident] for b in earlier if b and ident in b), box)
            found.append((ident, before, box, tick - first.get(ident, tick)))
        out[frame] = found
    return out


def _on(box, width, height):
    return sensor.finite_box(box) and box[0] >= 0 and box[1] >= 0 and box[2] <= width and box[3] <= height


def _region(before, now, side, width, height):
    """Top-left corners searched: the path's ends, rounded, and ``PAD`` beyond, clipped to the frame."""
    x0 = max(0, math.floor(min(before[0], now[0])) - PAD)
    y0 = max(0, math.floor(min(before[1], now[1])) - PAD)
    x1 = min(width - side, math.ceil(max(before[0], now[0])) + PAD)
    y1 = min(height - side, math.ceil(max(before[1], now[1])) + PAD)
    return x0, y0, x1, y1


def path_iou(box, before, now, samples=20):
    """The best overlap of ``box`` with the object's box anywhere on the straight path from ``before`` to ``now``."""
    return max(sensor._iou(box, [before[k] + (now[k] - before[k]) * j / samples for k in range(4)])
               for j in range(samples + 1))


def art_reference(rgba, side):
    """The approved art scaled to ``side`` (nearest, whole multiples only): its opaque footprint and the
    standardised luminance over it, which ``locate`` correlates with clean pixels."""
    np = numpy()
    height, width = rgba.shape[:2]
    if side % width or side % height or side // width != side // height:
        raise sensor.SensorError('the radial witness needs the drawn sprite to be a whole multiple of its art')
    scale = side // width
    big = np.kron(rgba.astype(np.float64), np.ones((scale, scale, 1)))
    footprint = big[..., 3] >= 250
    lum = 0.299 * big[..., 0] + 0.587 * big[..., 1] + 0.114 * big[..., 2]
    values = lum[footprint]
    if footprint.sum() < 8 or values.std() < 1:
        raise sensor.SensorError('the approved art is too flat to locate the sprite')
    return footprint, (values - values.mean()) / values.std()


def locate(rgb, before, now, side, footprint, reference):
    """(score, x, y): where on the path the approved art correlates best with the pixels, by luminance over its
    opaque footprint. Used on trusted clean frames only, to place the crops whose rings are frozen."""
    np = numpy()
    height, width = rgb.shape[:2]
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    x0, y0, x1, y1 = _region(before, now, side, width, height)
    best = (-1.0, None, None)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            values = lum[y:y + side, x:x + side][footprint]
            spread = values.std()
            if spread < 1:
                continue
            score = float(((values - values.mean()) / spread * reference).mean())
            if score > best[0]:
                best = (score, x, y)
    return best


def search(rgb, before, now, side, rings, profiles):
    """(distance, x, y): the position on the path whose rings are nearest a frozen profile; (inf, None, None)
    when no whole crop fits."""
    np = numpy()
    height, width = rgb.shape[:2]
    x0, y0, x1, y1 = _region(before, now, side, width, height)
    frozen = np.asarray(profiles, np.float64)
    index = _ring_index(side)
    masks = [index == k for k in range(rings)]
    counts = np.asarray([m.sum() for m in masks], np.float64)
    pixels = rgb.astype(np.float64)
    best = (math.inf, None, None)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            crop = pixels[y:y + side, x:x + side]
            means = np.concatenate([crop[m].sum(0) / c for m, c in zip(masks, counts)])
            d = float(np.abs(frozen - means).mean(axis=1).min())
            if d < best[0]:
                best = (d, x, y)
    return best


def _clear(box, everything):
    """Whether ``box`` touches no other logged box (``everything`` holds it once)."""
    from agents.template_foreground import _touches
    return sum(_touches(box, other) for other in everything) == 1


def _eligible(logged, others, width, height, side, fades):
    """The (id, before, now) of a frame worth judging in calibration: wholly on screen along the path, the
    logged size, clear of every other logged box, and not fading."""
    everything = [now for _, _, now, _ in logged] + others
    out = []
    for ident, before, now, age in logged:
        if not (_on(before, width, height) and _on(now, width, height)):
            continue
        if abs((now[2] - now[0]) - side) > 1 or abs((now[3] - now[1]) - side) > 1:
            continue
        if fades is not None and age >= fades:
            continue
        if _clear(now, everything):
            out.append((ident, before, now))
    return out


def _frames(root):
    record = json.loads((root / 'replay.json').read_text())
    trace = json.loads((root / 'trace.json').read_text())
    return record, trace, sensor.frame_files(root / 'frames')


def _others(trace, frames, fps, role):
    """{frame: boxes of every other logged object}: the player and every other role, for the clear rule."""
    player = sensor.player_predictions(trace, frames, fps)
    other = {r: sensor.object_predictions(trace, frames, r, fps) for r in sensor.OBJECT_BOXES if r != role}
    out = {}
    for n in frames:
        boxes = [player[n]['player']] if sensor.finite_box(player[n]['player']) else []
        for r in other:
            boxes += [b for _, b in (other[r][n] or [])]
        out[n] = boxes
    return out


def calibrate(clean_runs, validation_run, *, role, art_rgba, art, side, fades, clean_tree):
    """(witness, counts): ring profiles from the clean runs, validated on the separate clean validation run.

    ``art_rgba`` is the approved art's RGBA array, read by the caller from the pinned clean game, and ``art``
    its provenance ({path, sha256}). Every replay must be of the pinned clean tree with no patch. ``counts`` is
    the calibration record (template_foreground.py ``_object_calibration``) with ``witness: radial``."""
    from agents.template_foreground import _object_calibration
    from pathlib import Path

    np = numpy()
    Image, _, _ = sensor.imaging()
    rings = rings_for(side)
    footprint, reference = art_reference(np.asarray(art_rgba), side)
    kept = []
    seen = set()

    def clean(root):
        record, trace, files = _frames(root)
        if (record['game']['tree'] != clean_tree or record['game'].get('patch') is not None
                or record['game'].get('patchSha256') is not None
                or sensor.sha(root / 'trace.json') != record['trace']['sha256']):
            raise sensor.SensorError('the radial witness is calibrated on the pinned unpatched clean replay only')
        return record, trace, files

    for root in map(Path, clean_runs):
        record, trace, files = clean(root)
        seen.add(sensor.sha(root / 'replay.json'))
        fps = record['capture']['fps']
        where = paths(trace, list(files), role, fps)
        others = _others(trace, list(files), fps, role)
        for n, path in files.items():
            if not where.get(n):
                continue
            with Image.open(path) as image:
                rgb = np.asarray(image.convert('RGB'))
            height, width = rgb.shape[:2]
            for _, before, now in _eligible(where[n], others[n], width, height, side, fades):
                score, x, y = locate(rgb, before, now, side, footprint, reference)
                if x is None or score < LOCATE_FLOOR or path_iou([x, y, x + side, y + side], before, now) < 0.5:
                    continue
                ring = profile(rgb[y:y + side, x:x + side], rings)
                if kept and min(distance(ring, k) for k in kept) < DUPLICATE:
                    continue
                kept.append(ring)
                if len(kept) > MAX_PROFILES:
                    raise sensor.SensorError(f'the radial witness of {role} exceeds {MAX_PROFILES} profiles')
    profiles = [[round(float(v), 3) for v in ring] for ring in kept]
    witness = dict(algorithm=ALGORITHM, art=dict(art), sidePx=side, rings=rings, pathTicks=PATH_TICKS,
                   fadesAfterTicks=fades, locateFloor=LOCATE_FLOOR, maxDistance=MAX_DISTANCE,
                   profiles=profiles, profilesSha256=profiles_digest(profiles))
    root = Path(validation_run)
    record, trace, files = clean(root)
    if sensor.sha(root / 'replay.json') in seen:
        raise sensor.SensorError('the radial witness is validated on a separate clean replay')
    positives, negatives = [], []
    if profiles:
        fps = record['capture']['fps']
        where = paths(trace, list(files), role, fps)
        others = _others(trace, list(files), fps, role)
        for n, path in files.items():
            if not where.get(n):
                continue
            with Image.open(path) as image:
                rgb = np.asarray(image.convert('RGB'))
            height, width = rgb.shape[:2]
            everything = [now for _, _, now, _ in where[n]] + others[n]
            for _, before, now in _eligible(where[n], others[n], width, height, side, fades):
                found, _, _ = search(rgb, before, now, side, rings, profiles)
                positives.append(1 if found <= MAX_DISTANCE else 0)
                # One displaced beside it, clear of every logged object: nothing there should match.
                shift = side + 2 * PAD + 2 * 16 + 8
                for direction in (1, -1):
                    box = [now[0] + direction * shift, now[1], now[2] + direction * shift, now[3]]
                    if _on(box, width, height) and not any(_touches_any(box, o) for o in everything):
                        found, _, _ = search(rgb, box, box, side, rings, profiles)
                        negatives.append(1 if found <= MAX_DISTANCE else 0)
                        break
    counts = _object_calibration(positives, negatives, 1, len(profiles))
    counts['witness'] = 'radial'
    return witness, counts


def _touches_any(a, b):
    from agents.template_foreground import _touches
    return _touches(a, b)


def profiles_digest(profiles) -> str:
    return hashlib.sha256(json.dumps(profiles, separators=(',', ':')).encode()).hexdigest()


def check_witness(role, witness, counted):
    """Read a bank's radial witness back: its digest, its shape, its fixed settings, and a calibration record
    whose status is the one its counts give."""
    from agents.template_foreground import _object_calibration

    if witness['profilesSha256'] != profiles_digest(witness['profiles']):
        raise sensor.SensorError(f'the radial witness of {role} does not match its digest')
    if witness['rings'] != rings_for(witness['sidePx']):
        raise sensor.SensorError(f'the radial witness of {role} reads other rings than its size gives')
    if any(len(p) != 3 * witness['rings'] for p in witness['profiles']):
        raise sensor.SensorError(f'a ring profile of {role} has the wrong length')
    if (witness['pathTicks'], witness['locateFloor'], witness['maxDistance']) != (PATH_TICKS, LOCATE_FLOOR, MAX_DISTANCE):
        raise sensor.SensorError(f'the radial witness of {role} was calibrated with other settings than this reader')
    if counted.get('witness') != 'radial':
        raise sensor.SensorError(f'the calibration record of {role} does not name its radial witness')
    if counted['templates'] != len(witness['profiles']):
        raise sensor.SensorError(f'the calibration record of {role} does not count its ring profiles')
    if counted['positiveMatches'] > counted['positives'] or counted['negativeMatches'] > counted['negatives']:
        raise sensor.SensorError(f'calibrated object {role} records more matches than it counted')
    expected = _object_calibration([1] * counted['positiveMatches'] + [0] * (counted['positives'] - counted['positiveMatches']),
                                   [1] * counted['negativeMatches'] + [0] * (counted['negatives'] - counted['negativeMatches']),
                                   1, counted['templates'])
    if expected != {k: v for k, v in counted.items() if k != 'witness'}:
        raise sensor.SensorError(f'calibrated object {role} records a status its counts do not give')


def look(witness, rgb, before, now, age):
    """The witness's row for one logged object in one frame, in the shape template_observations.py ``look``
    gives: ``matched`` (``rawBox`` the matching position on the path), ``not-found``, ``out-of-frame`` (the path
    is not wholly on screen) or ``unavailable`` (fading, or not the calibrated size)."""
    side, rings, limit = witness['sidePx'], witness['rings'], witness['maxDistance']
    row = dict(status='unavailable', reason='', predictedBox=now, searchBox=None, rawBox=None, score=None,
               templateFrame=None, scale=None)
    height, width = rgb.shape[:2]
    if not (_on(before, width, height) and _on(now, width, height)):
        return dict(row, status='out-of-frame', reason='its path in this frame is not entirely on screen')
    if abs((now[2] - now[0]) - side) > 1 or abs((now[3] - now[1]) - side) > 1:
        return dict(row, reason=f'its logged box is not the {side}-pixel sprite the witness was calibrated on')
    fades = witness['fadesAfterTicks']
    if fades is not None and age >= fades:
        return dict(row, reason=f'it is {age} ticks old: the game fades it out from {fades}')
    found, x, y = search(rgb, before, now, side, rings, witness['profiles'])
    row['searchBox'] = list(_region(before, now, side, width, height))
    if x is None:
        return dict(row, reason='no whole crop fits on its path')
    # A score in the reference evaluator's terms: 0.5 exactly at the distance limit, 1 for identical rings.
    row['score'] = round(max(0.0, 1 - found / (2 * limit)), 6)
    if found > limit:
        return dict(row, status='not-found', reason='no position on its path has the clean rings')
    return dict(row, status='matched', reason='the clean rings are drawn on its path', rawBox=[x, y, x + side, y + side])
