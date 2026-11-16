"""Measure #515's public capture fixtures, offline; no engine and no model are called.

python3 -m tools.recorded_renderer --out docs/measurements/recorded-renderer.json
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / 'tests/fixtures/recorded-renderer'
RECORDING = ROOT / 'tests/outside/recordings/kinematic-character/vision-recording.json'


def metrics(reference, candidate, box):
    """RGBA differences and Euclidean distance to the original player's pixel centres.

    Box right/bottom are exclusive, as in the observations contract. Alpha is a channel too.
    Identical images have no changed-pixel distance, represented by null.
    """
    if reference.shape != candidate.shape:
        raise ValueError('image dimensions differ')
    delta = np.abs(reference.astype(np.int16) - candidate.astype(np.int16))
    ys, xs = np.where(np.any(delta, axis=2))
    dx = np.maximum(np.maximum(box[0] - xs, xs - (box[2] - 1)), 0)
    dy = np.maximum(np.maximum(box[1] - ys, ys - (box[3] - 1)), 0)
    distances = np.hypot(dx, dy)
    return {'changedPixels': len(xs), 'largestChannelDifference': int(delta.max()),
            'nearestPlayerDistancePx': round(float(distances.min()), 3) if len(xs) else None,
            'farthestPlayerDistancePx': round(float(distances.max()), 3) if len(xs) else None}


def cases(fixtures=FIXTURES, recording=RECORDING):
    fixtures = Path(fixtures)
    provenance = json.loads((fixtures / 'source.json').read_text())
    for name, digest in provenance['hashes'].items():
        if Path(name).name != name or hashlib.sha256((fixtures / name).read_bytes()).hexdigest() != digest:
            raise ValueError('fixture hash differs: ' + name)
    recording = json.loads(Path(recording).read_text())
    sha = provenance['hashes']['recorded.png']
    answer = next(a for a in recording['answers'] if a['frameSha256'] == sha and a['kind'] == 'segment-at')
    box = [int(v) for v in answer['detections'][0]['box']]
    def read(name):
        with Image.open(fixtures / name) as image:
            return np.array(image.convert('RGBA'))
    a, hidden = read('recorded.png'), read('hidden.png')
    x0, y0, x1, y1 = box
    # The real hidden capture supplies the background; assert that nothing else changed.
    mask = np.any(a != hidden, axis=2)
    mask[y0:y1, x0:x1] = False
    if np.any(mask):
        raise ValueError('the hidden capture changed pixels outside the player')
    result = [('renderer-frame-111', read('replayed.png'), 'real capture'),
              ('hidden-player', hidden, 'real seeded-bug capture')]
    moved = hidden.copy()
    moved[y0:y1, x0+3:x1+3] = a[y0:y1, x0:x1]
    result.append(('moved-right-3px', moved, 'synthetic compositing over the real hidden background'))
    resized = hidden.copy()
    resized[y0-2:y1+2, x0-2:x1+2] = np.array(Image.fromarray(a[y0:y1, x0:x1]).resize(
        (x1-x0+4, y1-y0+4), Image.Resampling.NEAREST))
    result.append(('resized-16-to-20px', resized, 'synthetic nearest-neighbour enlargement about the same centre'))
    result.append(('tinted-player', read('tinted.png'), 'real harmless/tinted capture'))
    faint = a.copy()
    faint[y0:y1, x0:x1, 0] = np.maximum(faint[y0:y1, x0:x1, 0].astype(int)-1, 0)
    result.append(('red-minus-one-whole-player', faint, 'synthetic one-level red reduction'))
    sparse = a.copy()
    sparse[y0+7, x0+7, 0] -= 1
    sparse[y0+8, x0+7, 1] -= 1
    result.append(('two-player-pixels-one-level', sparse, 'synthetic one-level recolour at two interior pixels'))
    return a, box, result


def measure(fixtures=FIXTURES, recording=RECORDING):
    fixtures = Path(fixtures)
    a, box, images = cases(fixtures, recording)
    before, after = [json.loads((fixtures / name).read_text()) for name in
                     ('recorded-replay.json', 'replayed-replay.json')]
    if len(before['frameSha256']) != len(after['frameSha256']):
        raise ValueError('captures have different lengths')
    changed = [n for n, (x, y) in enumerate(zip(before['frameSha256'], after['frameSha256'])) if x != y]
    if changed != [111]:
        raise ValueError('the committed pixel fixtures do not cover the differing frames')
    for replay, name in [(before, 'recorded.png'), (after, 'replayed.png')]:
        if replay['frameSha256'][111] != hashlib.sha256((fixtures/name).read_bytes()).hexdigest():
            raise ValueError('frame does not match capture record')
    rows = [{'case': label, 'source': source, **metrics(a, image, box)} for label, image, source in images]
    return {'framesCompared': len(before['frameSha256']), 'identicalFrames': len(before['frameSha256'])-len(changed),
            'differentFrames': changed, 'playerBox': box, 'recordedEnvironment': before['engine'],
            'replayedEnvironment': after['engine'], 'rows': rows,
            'decision': 'Keep exact matching: a sparse player recolour overlaps renderer drift in pixel count and maximum channel difference. Distance separates these fixtures, but no general protected-region matching rule is validated.'}


def table(doc):
    lines = ['| Comparison | Changed pixels | Largest channel difference (0–255) | Distance from player, min–max px |',
             '| --- | ---: | ---: | ---: |',
             f"| Renderer: {doc['identicalFrames']} identical frames | 0 | 0 | no changed pixels |"]
    for row in doc['rows']:
        lines.append(f"| {row['case']} | {row['changedPixels']} | {row['largestChannelDifference']} | "
                     f"{row['nearestPlayerDistancePx']}–{row['farthestPlayerDistancePx']} |")
    return '\n'.join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    doc = measure()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2)+'\n')
    print(table(doc))
    print('\n'+doc['decision'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
