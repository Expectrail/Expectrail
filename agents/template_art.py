"""Register a caller-selected clean RGBA pose catalogue on clean capture pixels.

Catalogue entries are configuration, not approval. Both the asset and its scene
reference stay inside the separately pinned clean game. Candidate pixels are never
read here. Derived poses retain their clean registration anchor and full byte provenance.
"""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

from agents import template_observations as sensor
from agents import template_foreground as foreground


def read_catalogue(value):
    if isinstance(value, dict):
        document = copy.deepcopy(value)
    else:
        data = Path(value).read_bytes()
        if len(data) > 1_000_000:
            raise sensor.SensorError('foreground catalogue is too large')
        document = json.loads(data)
    sensor.validate(document, 'template-foreground-catalogue')
    return document


def clean_path(game, relative):
    root, relative = Path(game).resolve(), Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise sensor.SensorError('catalogue paths must stay inside the trusted clean game')
    result = (root/relative).resolve()
    if root not in result.parents or not result.is_file():
        raise sensor.SensorError('catalogue path escapes the trusted clean game')
    return result


def attach_sources(game, sources, catalogue):
    np = foreground.numpy()
    Image, _, _ = sensor.imaging()
    entries = catalogue['objects']
    if set(entries) != {source['object'] for source in sources}:
        raise sensor.SensorError('catalogue must name exactly the selected foreground objects')
    for source in sources:
        entry = entries[source['object']]
        if Path(entry['artPath']).as_posix() != source['path']:
            raise sensor.SensorError('catalogue art path differs from the selected clean asset')
        scene = clean_path(game, entry['sourceScene']['path'])
        if sensor.sha(scene) != entry['sourceScene']['sha256']:
            raise sensor.SensorError('catalogue scene digest differs from the trusted clean reference')
        with Image.open(clean_path(game, source['path'])) as image:
            if image.width*image.height > 4_194_304:
                raise sensor.SensorError('catalogue RGBA art exceeds four megapixels')
            array = np.asarray(image.convert('RGBA'))
        source['artSize'] = [array.shape[1], array.shape[0]]
        source['rgbaPixels'], source['rgbaPixelsSha256'] = foreground.encode(array.tobytes())
        source['catalogue'] = copy.deepcopy(entry)
        check_source(source)


def check_source(source):
    np = foreground.numpy()
    entry = source['catalogue'];columns, rows = entry['spriteGrid'];width, height = source['artSize']
    if width % columns or height % rows:
        raise sensor.SensorError('catalogue grid does not divide its clean art')
    poses = entry['poses']
    if poses != sorted(set(poses)) or any(pose >= columns*rows for pose in poses):
        raise sensor.SensorError('catalogue poses must be sorted, unique and inside the grid')
    if entry['artPath'] != source['path']:
        raise sensor.SensorError('catalogue provenance names a different asset')
    relative = Path(entry['sourceScene']['path'])
    if relative.is_absolute() or '..' in relative.parts:
        raise sensor.SensorError('catalogue scene provenance escapes its clean game')
    raw = foreground.decode(source['rgbaPixels'], source['rgbaPixelsSha256'], width*height*4)
    array = np.frombuffer(raw, np.uint8).reshape(height, width, 4)
    opaque = array[..., 3] >= source['alphaMinimum']
    if not opaque.any() or not (array[..., 3] == 0).any():
        raise sensor.SensorError('catalogue art lacks opaque foreground or transparent background')
    actual = np.unique(array[..., :3][opaque], axis=0).tolist()
    if actual != source['paletteRgb']:
        raise sensor.SensorError('catalogue palette disagrees with its frozen RGBA bytes')
    return array


def pose_image(source, array, pose, scale):
    Image, _, _ = sensor.imaging()
    columns, rows = source['catalogue']['spriteGrid']
    width, height = source['artSize'][0]//columns, source['artSize'][1]//rows
    cell = array[(pose//columns)*height:(pose//columns+1)*height,
                 (pose % columns)*width:(pose % columns+1)*width]
    size = (max(1, round(width*scale)), max(1, round(height*scale)))
    if size[0]*size[1] > 16_777_216:
        raise sensor.SensorError('registered art scale exceeds sixteen megapixels')
    return Image.fromarray(cell).resize(size, Image.Resampling.NEAREST)


def crop_pose(source, array, pose, scale, offset, width, height):
    np = foreground.numpy()
    image = pose_image(source, array, pose, scale)
    x, y = offset
    rgba = np.asarray(image.crop((x, y, x+width, y+height)))
    mask = (rgba[..., 3] >= source['alphaMinimum']).astype(np.uint8)
    rgb = rgba[..., :3].copy()
    # A deterministic colour outside the art palette represents ignored transparency.
    codes = set(map(int, foreground.colour_codes(np.asarray(source['paletteRgb'], np.uint8))))
    sentinel = next(value for value in range(len(codes)+1) if value not in codes)
    rgb[mask == 0] = [sentinel//65536, sentinel//256 % 256, sentinel % 256]
    return rgb, mask


def agreement(rgb, mask, expected_rgb, expected_mask):
    np = foreground.numpy()
    matched = np.all(rgb == expected_rgb, axis=2) & mask.astype(bool) & expected_mask.astype(bool)
    total = int(mask.sum())+int(expected_mask.sum())
    return 2*int(matched.sum())/total if total else 0.0


def register(source, anchor):
    """Sparse colour correspondences propose translations; full clean RGB verifies each fit."""
    np = foreground.numpy()
    array = check_source(source)
    rgb = np.frombuffer(base64.b64decode(anchor['rgbPixels']), np.uint8).reshape(anchor['height'], anchor['width'], 3)
    mask = np.frombuffer(base64.b64decode(anchor['foregroundMask']), np.uint8).reshape(anchor['height'], anchor['width'])
    codes = foreground.colour_codes(rgb)
    values = np.unique(codes[mask.astype(bool)])
    locations = {int(value): np.column_stack(np.where(mask.astype(bool) & (codes == value))) for value in values}
    best = None
    # Fixed, versioned hypotheses for nearest-neighbour pixel art. A poor fit stops;
    # no arbitrary transform is inferred from candidate frames.
    for scale in (1, 1.5, 2, 2.5, 3, 4):
        for pose in source['catalogue']['poses']:
            image = pose_image(source, array, pose, scale)
            rendered = np.asarray(image);opaque = rendered[..., 3] >= source['alphaMinimum']
            code = foreground.colour_codes(rendered[..., :3])
            colours, counts = np.unique(code[opaque], return_counts=True)
            common = [(len(locations[int(value)])*int(count), int(value)) for value, count in zip(colours, counts) if int(value) in locations]
            if not common:
                continue
            _, colour = min(common)
            art_points = np.column_stack(np.where(opaque & (code == colour)))
            shifts = (art_points[:, None, :]-locations[colour][None, :, :]).reshape(-1, 2)
            unique, votes = np.unique(shifts, axis=0, return_counts=True)
            for index in np.argsort(votes, kind='stable')[-16:]:
                y, x = map(int, unique[index])
                expected_rgb, expected_mask = crop_pose(source, array, pose, scale, [x,y], anchor['width'], anchor['height'])
                score = agreement(rgb, mask, expected_rgb, expected_mask)
                key = (-score, pose, scale, y, x)
                if best is None or key < best[0]:
                    best = key, dict(anchorPose=pose, scale=scale, offset=[x,y], agreement=score,
                                     anchorRgbSha256=anchor['rgbPixelsSha256'])
    if best is None or best[1]['agreement'] < .98:
        raise sensor.SensorError('approved art catalogue could not be registered on clean capture pixels at 98% agreement')
    return best[1]


def extend_templates(bank):
    np = foreground.numpy()
    Image, _, _ = sensor.imaging()
    for source in bank['foregroundSources']:
        if 'catalogue' not in source:
            continue
        array = check_source(source)
        anchor = next((item for item in bank['templates'] if item['object'] == source['object'] and not item['mirrorX']), None)
        if anchor is None:
            raise sensor.SensorError('catalogue needs a clean capture registration anchor')
        registration = register(source, anchor)
        for pose in source['catalogue']['poses']:
            rgb, mask = crop_pose(source, array, pose, registration['scale'], registration['offset'], anchor['width'], anchor['height'])
            for mirrored in (False, True):
                pixels, foreground_mask = (rgb[:, ::-1], mask[:, ::-1]) if mirrored else (rgb, mask)
                if foreground.features(pixels, foreground_mask, bank['config']) is None:
                    continue
                item = copy.deepcopy(anchor)
                item.update(kind='approved-art-pose', mirrorX=mirrored, artRegistration=dict(registration, pose=pose))
                item['pixels'], item['pixelsSha256'] = foreground.encode(Image.fromarray(pixels).convert('L').tobytes())
                item['rgbPixels'], item['rgbPixelsSha256'] = foreground.encode(pixels.tobytes())
                item['foregroundMask'], item['foregroundMaskSha256'] = foreground.encode(foreground_mask.tobytes())
                bank['templates'].append(item)
                if len(bank['templates']) > 2048:
                    raise sensor.SensorError('foreground catalogue exceeds 2048 templates')


def check_registration(item, source, captures, cache):
    np = foreground.numpy()
    registration = item['artRegistration']
    if 'catalogue' not in source or registration['pose'] not in source['catalogue']['poses'] or registration['anchorPose'] not in source['catalogue']['poses']:
        raise sensor.SensorError('registered pose is outside its trusted art catalogue')
    anchors = [entry for entry in captures if entry['object'] == item['object']
               and entry['rgbPixelsSha256'] == registration['anchorRgbSha256']
               and all(entry[key] == item[key] for key in ('frame','frameSha256','sourceReplaySha256','box','predictedBox','width','height'))]
    if not anchors:
        raise sensor.SensorError('registered pose has no matching clean capture anchor')
    array = check_source(source) if source['object'] not in cache else cache[source['object']]
    cache[source['object']] = array
    rgb, mask = crop_pose(source, array, registration['pose'], registration['scale'], registration['offset'], item['width'], item['height'])
    if item['mirrorX']:
        rgb, mask = rgb[:, ::-1], mask[:, ::-1]
    if foreground.encode(rgb.tobytes())[1] != item['rgbPixelsSha256'] or foreground.encode(mask.tobytes())[1] != item['foregroundMaskSha256']:
        raise sensor.SensorError('registered pose pixels disagree with frozen clean RGBA art')
    anchor = anchors[0]
    expected_rgb, expected_mask = crop_pose(source, array, registration['anchorPose'], registration['scale'], registration['offset'], item['width'], item['height'])
    actual_rgb = np.frombuffer(base64.b64decode(anchor['rgbPixels']), np.uint8).reshape(item['height'], item['width'], 3)
    actual_mask = np.frombuffer(base64.b64decode(anchor['foregroundMask']), np.uint8).reshape(item['height'], item['width'])
    if anchor['mirrorX']:
        actual_rgb, actual_mask = actual_rgb[:, ::-1], actual_mask[:, ::-1]
    score = agreement(actual_rgb, actual_mask, expected_rgb, expected_mask)
    if score < .98 or abs(score-registration['agreement']) > 1e-8:
        raise sensor.SensorError('registered pose agreement differs from its clean anchor')
