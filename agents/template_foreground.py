"""Opt-in approved-art foreground witnesses for the template sensor. No model or network.

A clean RGBA asset supplies an opaque palette. Clean replay pixels in that palette
supply frozen foreground masks; candidate pixels never select masks or templates.
Masked luminance NCC proposes locations. RGB and four-part coverage confirm them.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
from pathlib import Path

from agents import template_observations as sensor

ALGORITHM = 'expectrail.template-foreground/v3'
FORMAT = 'expectrail.template-bank/v1'
DEFAULTS = dict(sensor.DEFAULTS, algorithm=ALGORITHM, foregroundPurity=0.95,
                rgbTolerance=2, rasterTolerancePx=1, confirmationCandidates=32,
                minimumForegroundBins=32, confirmationParts=4)
LIMITATIONS = [
    'Approved-art palette membership supplies masks on clean pixels; it is not semantic segmentation.',
    'A palette shared by other art can create ambiguity; clean negative validation is required.',
    'RGB confirms calibrated art but does not certify arbitrary colour or text specifications.',
    'Lighting, transparency, rotation, nonuniform scale and uncalibrated poses may be unsupported.',
    'Boxes locate calibrated rectangles, not the complete sprite silhouette.',
    'Search is local to the recorded engine prediction; that prediction is not visibility proof.',
    'Frozen clean collision regions are a reference map, not segmentation of current ground pixels.',
]
PIXEL_FIELDS = ('rgbPixels', 'rgbPixelsSha256', 'foregroundMask', 'foregroundMaskSha256')
# Named objects whose facing is calibrated (#286): each clean capture of one is labelled with the way the
# engine moved it on that tick (``heading``; its mirrored copy the other way), and ``facing`` decides which
# way a drawn one faces from its right- and left-labelled templates alone. The enemy only: the game flips its
# sprite with its velocity (game/platformer/enemy/enemy.gd). A pose that looks the same mirrored is labelled
# neither way: it cannot say which way it faces.
FACING_OBJECTS = ('enemy',)
# The facing decided is the heading whose templates match the drawn object better by at least this much.
FACING_MARGIN = 0.02
OPPOSITE = {'right': 'left', 'left': 'right'}


def numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise sensor.SensorError('foreground sensor needs NumPy; no model is used') from exc
    return np


def encode(data):
    return base64.b64encode(data).decode(), hashlib.sha256(data).hexdigest()


def decode(text, expected, length):
    try:
        raw = base64.b64decode(text, validate=True)
    except (ValueError, TypeError) as exc:
        raise sensor.SensorError('invalid foreground pixel encoding') from exc
    if len(raw) != length or hashlib.sha256(raw).hexdigest() != expected:
        raise sensor.SensorError('foreground pixel length or digest differs')
    return raw


def colour_codes(rgb):
    np = numpy()
    return rgb[..., 0].astype(np.uint32)*65536 + rgb[..., 1].astype(np.uint32)*256 + rgb[..., 2]


def art_sources(game, paths, clean_tree):
    """Read caller-selected art only inside the separately trusted, pinned clean tree."""
    from harness.run import tree_digest
    np = numpy()
    Image, _, _ = sensor.imaging()
    game = Path(game).resolve()
    if tree_digest(game) != clean_tree:
        raise sensor.SensorError('foreground art needs the pinned trusted clean game tree')
    sources = []
    for name, relative in sorted(paths.items()):
        relative = Path(relative)
        if relative.is_absolute() or '..' in relative.parts:
            raise sensor.SensorError('foreground art path must stay inside the trusted clean game')
        path = (game/relative).resolve()
        if game not in path.parents or not path.is_file():
            raise sensor.SensorError('foreground art path must stay inside the trusted clean game')
        with Image.open(path) as image:
            if image.width*image.height > 16_777_216 or 'A' not in image.getbands():
                raise sensor.SensorError('foreground art needs an RGBA alpha mask of at most 16 megapixels')
            array = np.asarray(image.convert('RGBA'))
        opaque = array[..., 3] >= 250
        if not opaque.any() or not (array[..., 3] == 0).any():
            raise sensor.SensorError('foreground art needs both opaque art and transparent background')
        palette = np.unique(array[..., :3][opaque], axis=0)
        if not 2 <= len(palette) <= 4096:
            raise sensor.SensorError('foreground art needs 2 to 4096 opaque palette colours')
        sources.append(dict(object=name, path=relative.as_posix(), sha256=sensor.sha(path),
                            alphaMinimum=250, paletteRgb=palette.tolist()))
    if not sources:
        raise sensor.SensorError('select at least one trusted foreground art asset')
    return sources


def features(rgb, mask, config):
    np = numpy()
    Image, _, _ = sensor.imaging()
    side = config['sampleSide']
    weights = (sensor._pooled(mask.astype(np.float32), side) >= config['foregroundPurity']).astype(np.float32)
    mass = float(weights.sum())
    if mass < config['minimumForegroundBins']:
        return None
    values = sensor._pooled(np.asarray(Image.fromarray(rgb).convert('L')), side)
    mean = float((values*weights).sum()/mass)
    centered = (values-mean)*weights
    norm = float(np.sqrt(np.dot(centered, centered)))
    if norm < config['minimumContrast']*math.sqrt(mass):
        return None
    return weights, centered/norm, mass


def check_bank(bank):
    """Validate mask provenance and internal byte consistency after schema validation."""
    np = numpy()
    Image, _, _ = sensor.imaging()
    config = bank['config']
    if config['minimumForegroundBins'] > config['sampleSide']**2:
        raise sensor.SensorError('minimum foreground bins exceeds the recorded sample grid')
    sources = {s['object']: s for s in bank['foregroundSources']}
    if len(sources) != len(bank['foregroundSources']):
        raise sensor.SensorError('duplicate foreground art source')
    for source in sources.values():
        if 'catalogue' in source:
            from agents import template_art
            template_art.check_source(source)
        path = Path(source['path'])
        if path.is_absolute() or '..' in path.parts:
            raise sensor.SensorError('foreground art provenance path escapes its clean game')
        palette = source['paletteRgb']
        if list(map(tuple, palette)) != sorted(set(map(tuple, palette))):
            raise sensor.SensorError('foreground art palette must be unique and sorted')
    registration_cache = {}
    captures = [item for item in bank['templates'] if item['kind'] == 'clean-capture']
    for item in bank['templates']:
        if item['object'] not in sources:
            raise sensor.SensorError('every foreground template needs its trusted art source')
        if item['kind'] == 'approved-art-pose':
            from agents import template_art
            template_art.check_registration(item, sources[item['object']], captures, registration_cache)
        height, width = item['height'], item['width']
        raw = decode(item['rgbPixels'], item['rgbPixelsSha256'], width*height*3)
        rgb = np.frombuffer(raw, np.uint8).reshape(height, width, 3)
        data = decode(item['foregroundMask'], item['foregroundMaskSha256'], width*height)
        mask = np.frombuffer(data, np.uint8).reshape(height, width)
        if not np.isin(mask, (0, 1)).all():
            raise sensor.SensorError('foreground mask must be binary')
        palette = np.asarray(sources[item['object']]['paletteRgb'], np.uint8)
        if not np.array_equal(mask, np.isin(colour_codes(rgb), colour_codes(palette))):
            raise sensor.SensorError('foreground mask does not follow its frozen approved-art palette')
        if Image.fromarray(rgb).convert('L').tobytes() != base64.b64decode(item['pixels']):
            raise sensor.SensorError('foreground RGB pixels disagree with the recorded luminance pixels')
        if features(rgb, mask, config) is None:
            raise sensor.SensorError('foreground template has insufficient opaque detail')
    witnesses = bank.get('radialWitnesses') or {}
    for role in witnesses:
        if role not in (bank['calibration'].get('objects') or {}):
            raise sensor.SensorError(f'the radial witness of {role} has no calibration record')
    for role, counted in (bank['calibration'].get('objects') or {}).items():
        if counted.get('witness') == 'radial' or role in witnesses:
            # Witnessed by its ring profiles (agents/template_radial.py), not by templates.
            from agents import template_radial
            if role not in witnesses:
                raise sensor.SensorError(f'calibrated object {role} names a radial witness the bank does not hold')
            if any(item['object'] == role for item in bank['templates']):
                raise sensor.SensorError(f'{role} is witnessed by its rings and also has templates')
            template_radial.check_witness(role, witnesses[role], counted)
            continue
        # A named object's record is recomputed from what it counts; it cannot claim templates it lacks,
        # matches it did not count, or a status its counts do not give.
        if role not in sources:
            raise sensor.SensorError(f'calibrated object {role} has no trusted art source')
        if counted['templates'] != sum(item['object'] == role for item in bank['templates']):
            raise sensor.SensorError(f'calibrated object {role} does not have the templates it records')
        if counted['positiveMatches'] > counted['positives'] or counted['negativeMatches'] > counted['negatives']:
            raise sensor.SensorError(f'calibrated object {role} records more matches than it counted')
        expected = _object_calibration([1]*counted['positiveMatches'] + [0]*(counted['positives']-counted['positiveMatches']),
                                       [1]*counted['negativeMatches'] + [0]*(counted['negatives']-counted['negativeMatches']),
                                       1, counted['templates'])
        if expected != {k: v for k, v in counted.items() if k != 'facing'}:
            raise sensor.SensorError(f'calibrated object {role} records a status its counts do not give')
        if 'facing' in counted:
            _check_facing(bank, role, counted['facing'], config)
    labelled = {item['object'] for item in bank['templates'] if 'heading' in item}
    for role in labelled:
        if 'facing' not in ((bank['calibration'].get('objects') or {}).get(role) or {}):
            raise sensor.SensorError(f'templates of {role} are labelled with a heading its calibration does not record')
    reference = bank.get('groundReference')
    if reference:
        if not any(source['replaySha256'] == reference['sourceReplaySha256']
                   and source['traceSha256'] == reference['sourceTraceSha256'] for source in bank['sources']):
            raise sensor.SensorError('ground reference is not bound to a clean calibration source')
        if any(len(polygon) < 3 or any(len(point) != 2 or any(
                type(v) not in (int, float) or not math.isfinite(v) for v in point) for point in polygon)
               for polygon in reference['polygons']):
            raise sensor.SensorError('invalid frozen clean ground polygon')


def _check_facing(bank, role, record, config):
    """A named object's facing record, read back: its object is one whose facing is calibrated, its template
    counts are the bank's, no labelled template is a clean capture that looks the same mirrored, its counts
    add up, and its status is the one they give."""
    np = numpy()
    if role not in FACING_OBJECTS:
        raise sensor.SensorError(f'the facing of {role} is not calibrated')
    labelled = [item for item in bank['templates'] if item['object'] == role and 'heading' in item]
    for item in labelled:
        if item['kind'] != 'clean-capture':
            raise sensor.SensorError(f'a heading is recorded on a {role} template that is not a clean capture')
        rgb = np.frombuffer(base64.b64decode(item['rgbPixels']), np.uint8).reshape(item['height'], item['width'], 3)
        mask = np.frombuffer(base64.b64decode(item['foregroundMask']), np.uint8).reshape(item['height'], item['width'])
        if symmetric(rgb, mask, config, bank['calibration'].get('selectionSimilarity', 0.995)):
            raise sensor.SensorError(f'a {role} template that looks the same mirrored is labelled with a heading')
    counts = {h: sum(item['heading'] == h for item in labelled) for h in sensor.HEADINGS}
    if record['templates'] != counts:
        raise sensor.SensorError(f'the facing of {role} does not have the labelled templates it records')
    if record['agree'] + record['disagree'] > record['moving'] or \
            record['mirroredAgree'] + record['mirroredDisagree'] > record['moving']:
        raise sensor.SensorError(f'the facing of {role} records more decisions than frames')
    expected = _facing_calibration(record['moving'], record['agree'], record['disagree'], record['mirroredAgree'],
                                   record['mirroredDisagree'], counts['right'], counts['left'], record['margin'])
    if expected != record:
        raise sensor.SensorError(f'the facing of {role} records a status its counts do not give')


class ForegroundMatcher:
    """Bounded masked-NCC proposals plus independent full-resolution foreground confirmation."""
    def __init__(self, templates, config):
        np = numpy()
        self.templates, self.config = templates, config
        self.rgb, self.masks, weights, vectors, masses = [], [], [], [], []
        for item in templates:
            rgb = np.frombuffer(base64.b64decode(item['rgbPixels']), np.uint8).reshape(item['height'], item['width'], 3)
            mask = np.frombuffer(base64.b64decode(item['foregroundMask']), np.uint8).reshape(item['height'], item['width'])
            feature = features(rgb, mask, config)
            if feature is None:
                raise sensor.SensorError('foreground template has insufficient opaque detail')
            weight, vector, mass = feature
            self.rgb.append(rgb); self.masks.append(mask)
            weights.append(weight); vectors.append(vector); masses.append(mass)
        self.weights, self.vectors, self.masses = np.stack(weights), np.stack(vectors), np.asarray(masses)

    def confirm(self, image, box, index):
        np = numpy()
        Image, _, _ = sensor.imaging()
        from PIL import ImageFilter
        rgb, mask = self.rgb[index], self.masks[index]
        width, height = box[2]-box[0], box[3]-box[1]
        if rgb.shape[:2] != (height, width):
            rgb = np.asarray(Image.fromarray(rgb).resize((width, height), Image.Resampling.NEAREST))
            mask = np.asarray(Image.fromarray(mask).resize((width, height), Image.Resampling.NEAREST))
        radius = self.config['rasterTolerancePx']
        if radius:
            mask = np.asarray(Image.fromarray(mask*255).filter(ImageFilter.MinFilter(2*radius+1))) > 0
        else:
            mask = mask.astype(bool)
        agreed = np.zeros((height, width), bool)
        x0, y0, x1, y1 = box
        for dy in range(-radius, radius+1):
            for dx in range(-radius, radius+1):
                xs = np.clip(np.arange(x0+dx, x1+dx), 0, image.shape[1]-1)
                ys = np.clip(np.arange(y0+dy, y1+dy), 0, image.shape[0]-1)
                observed = image[ys[:, None], xs]
                agreed |= np.max(np.abs(observed.astype(np.int16)-rgb.astype(np.int16)), axis=2) <= self.config['rgbTolerance']
        total = float((agreed & mask).sum()/mask.sum()) if mask.any() else 0.0
        parts = []
        for rows in np.array_split(np.arange(height), self.config['confirmationParts']):
            mass = int(mask[rows].sum())
            parts.append(float((agreed[rows] & mask[rows]).sum()/mass) if mass else 1.0)
        return total, parts

    def match(self, image, predicted):
        np = numpy()
        config, side = self.config, self.config['sampleSide']
        rgb = np.asarray(image.convert('RGB'))
        margin = config['searchMarginPx']
        roi = [max(0, math.floor(predicted[0])-margin), max(0, math.floor(predicted[1])-margin),
               min(image.width, math.ceil(predicted[2])+margin), min(image.height, math.ceil(predicted[3])+margin)]
        array = np.asarray(image.convert('L').crop(roi), np.float64)
        integral = np.pad(array.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        groups = {}
        for index, item in enumerate(self.templates):
            original = item['predictedBox']
            ratio = min((predicted[2]-predicted[0])/(original[2]-original[0]),
                        (predicted[3]-predicted[1])/(original[3]-original[1]))
            for order, factor in enumerate(config['scales']):
                scale = ratio*factor
                size = (max(4, round(item['width']*scale)), max(4, round(item['height']*scale)))
                groups.setdefault(size, []).append((index, order, scale))
        proposals = {}
        for (width, height), entries in groups.items():
            xmax, ymax = array.shape[1]-width, array.shape[0]-height
            if xmax < 0 or ymax < 0:
                continue
            xs = np.floor(np.arange(side)*width/side).astype(int)
            xe = np.maximum(xs+1, np.floor(np.arange(1, side+1)*width/side).astype(int))
            ys = np.floor(np.arange(side)*height/side).astype(int)
            ye = np.maximum(ys+1, np.floor(np.arange(1, side+1)*height/side).astype(int))
            xa, ya = np.meshgrid(xs, ys); xb, yb = np.meshgrid(xe, ye)
            xa, ya, xb, yb = [value.ravel() for value in (xa, ya, xb, yb)]
            areas = (xb-xa)*(yb-ya)
            ids = [entry[0] for entry in entries]
            weights, vectors, mass = self.weights[ids], self.vectors[ids], self.masses[ids]
            for start in range(0, (xmax+1)*(ymax+1), 256):
                positions = np.arange(start, min(start+256, (xmax+1)*(ymax+1)))
                x = (positions % (xmax+1))[:, None]; y = (positions // (xmax+1))[:, None]
                samples = ((integral[y+yb, x+xb]-integral[y+ya, x+xb]
                            -integral[y+yb, x+xa]+integral[y+ya, x+xa])/areas).astype(np.float32)
                sums, squares = samples @ weights.T, (samples*samples) @ weights.T
                norms = np.sqrt(np.maximum(0, squares-sums*sums/mass))
                scores = np.clip((samples @ vectors.T)/np.maximum(norms, 1e-8), 0, 1)
                scores[norms < config['minimumContrast']*np.sqrt(mass)] = 0
                # Keep a distinct proposal for each template and scale. A plateau of
                # neighbouring positions for one pose must not consume the whole RGB budget.
                rounded = np.round(scores.astype(np.float64), 7)
                values = rounded.max(axis=0)
                centers_x = x[:, 0]+roi[0]+width/2
                centers_y = y[:, 0]+roi[1]+height/2
                distance = ((centers_x-(predicted[0]+predicted[2])/2)**2
                            +(centers_y-(predicted[1]+predicted[3])/2)**2)
                rows = np.where(rounded == values, distance[:, None], np.inf).argmin(axis=0)
                for column, pos in enumerate(rows):
                    index, order, scale = entries[column]
                    px, py = int(x[pos, 0])+roi[0], int(y[pos, 0])+roi[1]
                    value = float(scores[pos, column])
                    overlap = sensor._iou([px, py, px+width, py+height], predicted)
                    key = (-round(value, 7), -round(overlap, 7), py, px)
                    prior = proposals.get((index, order))
                    if prior is None or key < prior[0]:
                        proposals[(index, order)] = (key, (value, index, order, py, px, width, height, scale))
        candidates = [value for _, value in proposals.values()]
        candidates.sort(key=lambda item: (-round(item[0], 7), *item[1:5]))
        candidates = candidates[:config['confirmationCandidates']]
        if not candidates:
            raise sensor.SensorError('no configured foreground template size fits the search region')
        best = best_key = None
        for ncc, index, order, py, px, width, height, scale in candidates:
            bound_key = (-round(ncc, 7), index, order, py, px)
            if best_key is not None and bound_key >= best_key:
                break
            box = [px, py, px+width, py+height]
            if ncc < config['matchThreshold']:
                coverage, parts, score = None, None, 0.0
            else:
                coverage, parts = self.confirm(rgb, box, index)
                score = min(ncc, coverage, *parts)
            key = (-round(score, 7), index, order, py, px)
            if best_key is None or key < best_key:
                best_key = key
                best = dict(box=box, score=score, templateFrame=self.templates[index]['frame'], scale=scale,
                            components=dict(ncc=ncc, foregroundCoverage=coverage, partCoverage=parts))
        return best, roi


def symmetric(rgb, mask, config, similarity):
    """Whether a crop looks the same mirrored, by the rule that keeps two templates apart: a pose for which
    it does cannot say which way it faces, so it gets no ``heading``."""
    np = numpy()
    one, other = features(rgb, mask, config), features(rgb[:, ::-1], mask[:, ::-1], config)
    if one is None or other is None:
        return True
    (w1, v1, m1), (w2, v2, m2) = one, other
    intersection = float(np.dot(w1, w2))
    return float(np.dot(v1, v2)) >= similarity and intersection/(m1+m2-intersection) >= .9


def heading_matchers(templates, config):
    """{'right': matcher, 'left': matcher} over the templates labelled each way, or None without both."""
    by = {h: [t for t in templates if t.get('heading') == h] for h in sensor.HEADINGS}
    if not all(by.values()):
        return None
    return {h: ForegroundMatcher(items, config) for h, items in by.items()}


def facing(matchers, image, box, config, margin=FACING_MARGIN):
    """Which way the object drawn at ``box`` faces: {'facing': 'right' | 'left' | None, 'scores': {...}}.

    Each heading's score is its best confirmed match overlapping ``box`` (0 when none does). The facing is the
    heading that scores at least the match threshold and beats the other by ``margin``; otherwise None: the
    sensor cannot tell, which a check reads as a gap, never as either way."""
    scores = {}
    for heading in sensor.HEADINGS:
        found, _ = matchers[heading].match(image, box)
        ok = found is not None and sensor._iou(found['box'], box) >= config['agreementIoU']
        scores[heading] = round(float(found['score']), 6) if ok else 0.0
    best = max(sensor.HEADINGS, key=lambda h: (scores[h], h == 'right'))
    other = OPPOSITE[best]
    decided = scores[best] >= config['matchThreshold'] and scores[best] - scores[other] >= margin
    return {'facing': best if decided else None, 'scores': scores}


def mirrored_about(image, box):
    """``image`` with the region around ``box`` mirrored about the box's centre: the object drawn there now
    faces the other way. The region is the box widened by its own width each side, clipped evenly."""
    Image, _, _ = sensor.imaging()
    centre = (box[0]+box[2])/2
    half = min(box[2]-box[0], centre, image.width-centre)
    left, right = max(0, round(centre-half)), min(image.width, round(centre+half))
    top, bottom = max(0, math.floor(box[1])), min(image.height, math.ceil(box[3]))
    out = image.copy()
    if right-left >= 2 and bottom > top:
        region = image.crop((left, top, right, bottom)).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        out.paste(region, (left, top))
    return out


def _facing_calibration(moving, agree, disagree, mirrored_agree, mirrored_disagree, right, left, margin):
    """A named object's facing on the validation replay. ``moving`` frames show it moving one way; on each,
    the drawn object (``agree`` / ``disagree``: decided its way or the other) and the same frame with it
    mirrored (``mirroredAgree`` / ``mirroredDisagree``: decided the other way or its way). ``met`` by the
    player's rule on both: at least 95% decided right and at most 1% decided wrong, with templates both ways."""
    met = bool(right and left and moving and agree/moving >= .95 and disagree/moving <= .01
               and mirrored_agree/moving >= .95 and mirrored_disagree/moving <= .01)
    return dict(margin=margin, templates=dict(right=right, left=left), moving=moving, agree=agree,
                disagree=disagree, mirroredAgree=mirrored_agree, mirroredDisagree=mirrored_disagree,
                status='met' if met else 'unmet')


def _touches(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _calibration_boxes(trace, frames, fps, objects, size, ids=None):
    """{frame: {name: box}}: where calibration crops each object in each clean frame.

    The player wherever its box is wholly on screen. For each role in ``objects`` (the game has many of
    them; agents/template_observations.py ``object_predictions``), the lowest-id one whose logged box is
    wholly on screen and touches no other logged box of any object, so a crop never holds two sprites.
    ``ids``, when given, is filled with {frame: {role: id}}: which one was chosen."""
    width, height = size

    def on(b):
        return sensor.finite_box(b) and b[0] >= 0 and b[1] >= 0 and b[2] <= width and b[3] <= height

    player = sensor.player_predictions(trace, frames, fps)
    logged = {role: sensor.object_predictions(trace, frames, role, fps) for role in objects}
    out = {}
    for n in frames:
        everything = [b for b in [player[n]['player']] if sensor.finite_box(b)]
        for role in objects:
            everything += [b for _, b in (logged[role][n] or [])]
        chosen = {}
        if on(player[n]['player']):
            chosen['player'] = player[n]['player']
        for role in objects:
            for ident, box in sorted(logged[role][n] or [], key=lambda e: e[0]):
                if on(box) and sum(_touches(box, other) for other in everything) == 1:
                    chosen[role] = box
                    if ids is not None:
                        ids.setdefault(n, {})[role] = ident
                    break
        if chosen:
            out[n] = chosen
    return out


def _distinct(path, box, config):
    """Whether the clean crop at ``box`` passes the bank's contrast rule (template_observations ``load_bank``)."""
    Image, _, _ = sensor.imaging()
    crop = sensor._calibration_crop(box)
    with Image.open(path) as image:
        patch = image.convert('L').crop(crop)
    sample = patch.resize((config['sampleSide'],)*2, Image.Resampling.BOX)
    return min(sensor._contrast(patch), sensor._contrast(sample)) >= config['minimumContrast']


def _validate(matcher, settings, image, box, positives, negatives):
    """One validation frame: the match at the engine's box is a positive, one displaced beside it a negative."""
    found, _ = matcher.match(image, box)
    positives.append(found['score'] if found and sensor._iou(found['box'], box) >= settings['agreementIoU'] else 0)
    distance = box[2]-box[0]+2*settings['searchMarginPx']+8
    for direction in (1, -1):
        negative = [box[0]+direction*distance, box[1], box[2]+direction*distance, box[3]]
        if negative[0] >= 0 and negative[2] <= image.width:
            found, _ = matcher.match(image, negative)
            negatives.append(found['score'] if found else 0)
            break


def _object_calibration(positives, negatives, threshold, templates):
    """One named object's validation at the player's chosen threshold: ``met`` when at least 95% of its
    positives and at most 1% of its negatives match, the player's rule; ``unmet`` otherwise, including when
    it has no templates, no positives or no negatives to count."""
    matched = sum(value >= threshold for value in positives)
    false = sum(value >= threshold for value in negatives)
    met = bool(templates and positives and negatives and matched/len(positives) >= .95 and false/len(negatives) <= .01)
    return dict(templates=templates, positives=len(positives), negatives=len(negatives), positiveMatches=matched,
                negativeMatches=false, status='met' if met else 'unmet')


def _validate_facing(templates, config, files, trace, fps, role, boxes, ids, margin=FACING_MARGIN):
    """``_facing_calibration`` of ``role`` on the validation replay, at the bank's chosen threshold: every frame
    whose calibration crop shows the object moving one way is decided as drawn, and again mirrored."""
    Image, _, _ = sensor.imaging()
    right = sum(t.get('heading') == 'right' for t in templates)
    left = sum(t.get('heading') == 'left' for t in templates)
    matchers = heading_matchers(templates, config)
    moves = sensor.object_motion(trace, list(files), role, fps)
    moving = agree = disagree = mirrored_agree = mirrored_disagree = 0
    for n, path in files.items():
        box, ident = (boxes.get(n) or {}).get(role), (ids.get(n) or {}).get(role)
        motion = (moves.get(n) or {}).get(ident)
        if box is None or motion not in sensor.HEADINGS or matchers is None:
            continue
        moving += 1
        with Image.open(path) as image:
            image = image.convert('RGB')
            drawn = facing(matchers, image, box, config, margin)['facing']
            flipped = facing(matchers, mirrored_about(image, box), box, config, margin)['facing']
        agree += drawn == motion
        disagree += drawn == OPPOSITE[motion]
        mirrored_agree += flipped == OPPOSITE[motion]
        mirrored_disagree += flipped == motion
    return _facing_calibration(moving, agree, disagree, mirrored_agree, mirrored_disagree, right, left, margin)


def calibrate_routes(clean_runs, validation_run, *, clean_game, clean_tree, art, config=None, similarity=0.995, catalogue=None,
                     objects=()):
    """Freeze foreground witnesses from every eligible clean frame, then validate separately.

    ``objects`` names roles the game has many of (``enemy``, ``bullet``) to calibrate as well, each from the
    boxes the engine logs for it and its own approved art in ``art``. The match threshold is chosen on the
    player, as before; each named object's positives and negatives on the validation replay at that threshold
    are recorded under ``calibration.objects`` with its own ``met`` or ``unmet``, never folded into the player's."""
    objects = tuple(objects)
    if len(set(objects)) != len(objects) or any(r not in sensor.OBJECT_BOXES for r in objects):
        raise sensor.SensorError('named objects are distinct roles the engine logs boxes for: '
                                 + ', '.join(sorted(sensor.OBJECT_BOXES)))
    if any(role not in art for role in objects):
        raise sensor.SensorError('select approved art for every calibrated object')
    np = numpy()
    Image, _, _ = sensor.imaging()
    settings = dict(DEFAULTS, **(config or {}))
    if settings['algorithm'] != ALGORITHM or settings['matchThreshold'] < .9:
        raise sensor.SensorError('foreground calibration needs its versioned algorithm and a floor of at least 0.90')
    source_art = art_sources(clean_game, art, clean_tree)
    original_sources = copy.deepcopy(source_art)
    if catalogue is not None:
        from agents import template_art
        catalogue = template_art.read_catalogue(catalogue)
        # The catalogue adds poses for the objects it names (the player); a named object it does not name keeps
        # its captured templates only. It may not name an object that was not selected.
        template_art.attach_sources(clean_game, [s for s in source_art if s['object'] in catalogue['objects']
                                                 or s['object'] not in objects], catalogue)
    palettes = {item['object']: colour_codes(np.asarray(item['paletteRgb'], np.uint8)) for item in source_art}
    selected, vectors, masks, sources = [], [], [], []
    # (route index, frame, role) -> the way the engine moved the cropped object on that frame's tick.
    headings, sources_seen = {}, -1
    bank, source_frames, eligible_frames, ground = None, 0, 0, None
    for root in map(Path, clean_runs):
        sources_seen += 1
        record = json.loads((root/'replay.json').read_text())
        trace = json.loads((root/'trace.json').read_text())
        if (record['game']['tree'] != clean_tree or record['game'].get('patch') is not None
                or record['game'].get('patchSha256') is not None
                or sensor.sha(root/'trace.json') != record['trace']['sha256']):
            raise sensor.SensorError('foreground calibration requires the pinned unpatched clean replay')
        files = sensor.frame_files(root/'frames')
        base_config = {key: settings[key] for key in sensor.DEFAULTS}
        base_config['algorithm'] = sensor.ALGORITHM
        # Off-screen calibration crops are ineligible; they do not become smaller positives.
        predicted = None
        if objects:
            first = next(iter(files.values()), None)
            if first is None:
                raise sensor.SensorError('no eligible foreground calibration frames')
            with Image.open(first) as image:
                size = image.size
            chosen_ids = {}
            predicted = _calibration_boxes(trace, list(files), record['capture']['fps'], objects, size, chosen_ids)
            for role in objects:
                if role in FACING_OBJECTS:
                    moves = sensor.object_motion(trace, list(files), role, record['capture']['fps'])
                    for n, picked in chosen_ids.items():
                        if role in picked:
                            headings[(sources_seen, n, role)] = (moves.get(n) or {}).get(picked[role])
            # A named object's crop too flat to identify a sprite (the bank's own contrast rule) is not a
            # template; it is left out here rather than failing the calibration. The player's rule is unchanged.
            for n, chosen in list(predicted.items()):
                for role in objects:
                    if role in chosen and not _distinct(files[n], chosen[role], base_config):
                        del chosen[role]
                if not chosen:
                    del predicted[n]
            chosen_frames = sorted(predicted)
        else:
            predictions = sensor.player_predictions(trace, files, record['capture']['fps'])
            # Reuse the existing clean-source and PNG/trace binding checks, with full crops.
            eligible = [n for n, boxes in predictions.items() if sensor.finite_box(boxes['player'])]
            chosen_frames = []
            for n in eligible:
                with Image.open(files[n]) as image:
                    box = predictions[n]['player']
                    if box[0] >= 0 and box[1] >= 0 and box[2] <= image.width and box[3] <= image.height:
                        chosen_frames.append(n)
        if not chosen_frames:
            raise sensor.SensorError('no eligible foreground calibration frames')
        source = sensor.calibrate(root, clean_tree=clean_tree, frames=chosen_frames, config=base_config,
                                  predicted=predicted)
        bank = bank or source
        sources.append(source['clean']); source_frames += len(files)
        if trace.get('levelSurfaces'):
            if ground is not None and ground['polygons'] != trace['levelSurfaces']:
                raise sensor.SensorError('clean ground regions changed across calibration routes')
            ground = ground or dict(coordinates='trusted clean world coordinates; y down',
                                   sourceReplaySha256=source['clean']['replaySha256'],
                                   sourceTraceSha256=source['clean']['traceSha256'], polygons=trace['levelSurfaces'])
        for original in source['templates']:
            name = original['object']
            if name not in palettes:
                raise sensor.SensorError('select approved art for every calibrated object')
            with Image.open(files[original['frame']]) as image:
                rgb = np.asarray(image.convert('RGB').crop(original['box']))
            mask = np.isin(colour_codes(rgb), palettes[name]).astype(np.uint8)
            feature = features(rgb, mask, settings)
            if feature is None:
                continue
            eligible_frames += 1
            heading = headings.get((sources_seen, original['frame'], name))
            if heading not in sensor.HEADINGS or symmetric(rgb, mask, settings, similarity):
                heading = None
            for mirrored in (False, True):
                pixels = rgb[:, ::-1] if mirrored else rgb
                foreground = mask[:, ::-1] if mirrored else mask
                mirrored_feature = features(pixels, foreground, settings)
                if mirrored_feature is None:
                    continue
                weights, vector, mass = mirrored_feature
                # Distinct appearances are kept per object: one object's template never stands for another's.
                same = [i for i, kept in enumerate(selected) if kept['object'] == name]
                if same:
                    similarities = np.asarray([vectors[i] for i in same]) @ vector
                    kept_masks = np.asarray([masks[i] for i in same])
                    intersection = kept_masks @ weights
                    union = kept_masks.sum(1)+mass-intersection
                    if np.any((similarities >= similarity) & (intersection/union >= .9)):
                        continue
                item = copy.deepcopy(original)
                item['mirrorX'] = mirrored
                item['kind'] = 'clean-capture'
                if heading is not None:
                    item['heading'] = OPPOSITE[heading] if mirrored else heading
                item['pixels'], item['pixelsSha256'] = encode(Image.fromarray(pixels).convert('L').tobytes())
                item['rgbPixels'], item['rgbPixelsSha256'] = encode(pixels.tobytes())
                item['foregroundMask'], item['foregroundMaskSha256'] = encode(foreground.tobytes())
                selected.append(item); vectors.append(vector); masks.append(weights)
                if len(selected) > 2048:
                    raise sensor.SensorError('foreground calibration exceeds 2048 templates')
    if not any(item['object'] == 'player' for item in selected):
        raise sensor.SensorError('no clean foreground templates have enough opaque detail')
    bank.update(format=FORMAT, config=settings, templates=selected, sources=sources, foregroundSources=source_art)
    if ground:
        bank['groundReference'] = ground
    if catalogue is not None:
        template_art.extend_templates(bank)
    bank['calibration'].update(selection='approved-foreground', selectionSimilarity=similarity,
                               sourceFrames=source_frames, eligibleFrames=eligible_frames, mirrored=True)
    # Read back before validation. Headings are recorded with the facing validation below, so they are read
    # back with it, at the end; here the bank is read without them.
    unlabelled = copy.deepcopy(bank)
    for item in unlabelled['templates']:
        item.pop('heading', None)
    sensor.load_bank(unlabelled)
    root = Path(validation_run)
    record = json.loads((root/'replay.json').read_text())
    if record['game']['tree'] != clean_tree or record['game'].get('patch') is not None or record['game'].get('patchSha256') is not None:
        raise sensor.SensorError('foreground validation requires a pinned unpatched clean replay')
    if sensor.sha(root/'trace.json') != record['trace']['sha256']:
        raise sensor.SensorError('foreground validation trace digest differs')
    if sensor.sha(root/'replay.json') in {source['replaySha256'] for source in sources}:
        raise sensor.SensorError('foreground validation must be a separate clean replay')
    trace = json.loads((root/'trace.json').read_text())
    files = sensor.frame_files(root/'frames')
    boxes = sensor.player_predictions(trace, files, record['capture']['fps'])
    matcher = ForegroundMatcher([item for item in selected if item['object'] == 'player'], settings)
    named = {role: ForegroundMatcher(items, settings) for role in objects
             if (items := [item for item in selected if item['object'] == role])}
    named_boxes = None
    positives, negatives = [], []
    by_role = {role: ([], []) for role in named}
    for n, path in files.items():
        if n >= len(record['frameSha256']) or sensor.sha(path) != record['frameSha256'][n]:
            raise sensor.SensorError('foreground validation pixels differ from their replay')
        with Image.open(path) as image:
            image = image.convert('RGB')
            if named and named_boxes is None:
                named_ids = {}
                named_boxes = _calibration_boxes(trace, list(files), record['capture']['fps'], tuple(named), image.size,
                                                 named_ids)
            for role in named:
                box = (named_boxes.get(n) or {}).get(role)
                if box is not None:
                    _validate(named[role], settings, image, box, *by_role[role])
            box = boxes[n]['player']
            if not sensor.finite_box(box) or box[0] < 0 or box[1] < 0 or box[2] > image.width or box[3] > image.height:
                continue
            _validate(matcher, settings, image, box, positives, negatives)
    floor = settings['matchThreshold']; chosen, status = floor, 'unmet'
    for threshold in sorted({floor} | {n/100 for n in range(math.ceil(floor*100), 101)}):
        if positives and negatives and sum(value >= threshold for value in positives)/len(positives) >= .95 and sum(value >= threshold for value in negatives)/len(negatives) <= .01:
            chosen, status = threshold, 'met'
            break
    bank['config']['matchThreshold'] = chosen
    validation_sha = sensor.sha(root/'replay.json')
    bank['sources'].append(dict(gameTree=clean_tree, replaySha256=validation_sha, traceSha256=record['trace']['sha256']))
    bank['calibration'].update(thresholdFloor=floor, thresholdSelected=chosen,
        validationReplaySha256=validation_sha, positives=len(positives), negatives=len(negatives),
        positiveMatches=sum(value >= chosen for value in positives), negativeMatches=sum(value >= chosen for value in negatives), status=status)
    if objects:
        bank['calibration']['objects'] = {
            role: _object_calibration(*by_role.get(role, ([], [])), chosen, sum(item['object'] == role for item in selected))
            for role in objects}
        for role in objects:
            if role in FACING_OBJECTS:
                bank['calibration']['objects'][role]['facing'] = _validate_facing(
                    [item for item in selected if item['object'] == role], bank['config'], files, trace,
                    record['capture']['fps'], role, named_boxes or {}, named_ids if named_boxes else {})
    # The clean checkout remains the source authority throughout calibration.
    if art_sources(clean_game, art, clean_tree) != original_sources:
        raise sensor.SensorError('trusted foreground art changed during calibration')
    return sensor.load_bank(bank)
