"""Opt-in, offline observer calibration (#330): propose, score, prove, bind to art.

No client is constructed here. Adapters supply pixel detections or an explicit gap. Selection
frames choose a prompt/floor; disjoint proof frames never change them. This is separate from
anchored point calibration: its RULES and Sean's November 14 decisions are unchanged.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path, PurePosixPath

from expectrail import resources
from expectrail.contracts import digest, strict_loads
from expectrail.gate.record import errors
from expectrail.gate.verify import NoAnswer

FORMAT = 'expectrail.observer-calibration/v1'
BROKEN = ('hidden', 'behind-scenery', 'texture-blanked', 'shifted-off-body')
MIN_FRAMES, IOU, MARGIN = 8, 0.5, 0.05
MAX_BYTES = 8 * 1024 * 1024


class CalibrationError(ValueError):
    """Invalid evidence, not a negative pixel answer."""


def art_digests(game, paths):
    """Hash named texture bytes only. Refuse missing files, links and paths outside the game."""
    root = Path(game).resolve(strict=True)
    out = {}
    for name in sorted(paths):
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or '..' in path.parts or str(path) != name or '\\' in name):
            raise CalibrationError('texture paths must be relative, normal paths inside the game')
        current = root
        for part in path.parts:
            current = current / part
            if current.is_symlink():
                raise CalibrationError(f'texture path is a link: {name}')
        try:
            if not current.is_file() or current.stat().st_size > 64 * 1024 * 1024:
                raise CalibrationError(f'texture is missing or too large: {name}')
            out[name] = hashlib.sha256(current.read_bytes()).hexdigest()
        except OSError as exc:
            raise CalibrationError(f'texture cannot be read: {name}') from exc
    if not out or len(out) > 64:
        raise CalibrationError('name between 1 and 64 texture files')
    return out


def _iou(a, b):
    overlap = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    return overlap / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - overlap)


def _correct(row):
    return [d for d in row['detections'] if row['expectedBox'] is not None and _iou(d['box'], row['expectedBox']) >= IOU]


def status(row, floor):
    """Unknown is not absent; an extra above-floor box is not a unique player."""
    if row['error'] is not None or row['expectedBox'] is None:
        return 'unavailable'
    kept = [d for d in row['detections'] if d['score'] >= floor]
    return 'pass' if len(kept) == 1 and _iou(kept[0]['box'], row['expectedBox']) >= IOU else 'fail'


def _floor(rows, minimum):
    scores = [max((d['score'] for d in _correct(r)), default=0) for r in rows]
    return round(max(minimum, min(scores, default=0)-MARGIN), 6)


def _all_pass(rows, floor):
    return len(rows) >= MIN_FRAMES and all(status(r, floor) == 'pass' for r in rows)


def _derived(doc):
    candidates = doc['candidates']
    eligible = [c for c in candidates if _all_pass(c['rows'], c['floor'])]
    # Greatest lowest clean confidence wins; the phrase breaks ties reproducibly.
    selected = min(eligible, key=lambda c: (-c['floor'], c['prompt']))['prompt'] if eligible else None
    why, missed = [], []
    if selected is None:
        why.append('no candidate finds exactly one correct player on every selection frame')
        missed = list(BROKEN)
    else:
        floor = next(c['floor'] for c in candidates if c['prompt'] == selected)
        if not _all_pass(doc['clean'], floor):
            why.append('clean proof did not pass on every requested frame')
        for variant in doc['broken']:
            states = [status(r, floor) for r in variant['rows']]
            # A gap never proves a bug, even if another frame has a negative answer.
            if len(states) < MIN_FRAMES or 'unavailable' in states or 'fail' not in states:
                missed.append(variant['name'])
        if missed:
            why.append('broken copies not proved: '+', '.join(missed))
    return selected, not why, why, missed


def check(doc):
    try:
        json.dumps(doc, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise CalibrationError('calibration is not finite JSON') from exc
    found = errors(doc, json.loads((resources.ROOT/'contracts/observer-calibration.v1.schema.json').read_text()))
    if found:
        raise CalibrationError(f'observer calibration schema: {found[0]}')
    if digest(doc['art']) != doc['artSha256']:
        raise CalibrationError('texture digest summary disagrees with its files')
    if set(v['name'] for v in doc['broken']) != set(BROKEN) or len(doc['broken']) != len(BROKEN):
        raise CalibrationError('record every named broken copy exactly once')
    if len({c['prompt'] for c in doc['candidates']}) != len(doc['candidates']):
        raise CalibrationError('candidate prompts are duplicated')
    selection_ids = None
    for c in doc['candidates']:
        if c['floor'] != _floor(c['rows'], doc['minimumFloor']):
            raise CalibrationError('floor must come from selection frames only')
        ids = [(r['frame'], r['frameSha256'], r['replaySha256'], r['expectedBox']) for r in c['rows']]
        if selection_ids is not None and ids != selection_ids:
            raise CalibrationError('candidates must be scored on the same selection frames')
        selection_ids = ids
    selection_hashes = {r['frameSha256'] for c in doc['candidates'] for r in c['rows']}
    for rows in [doc['clean'], *(v['rows'] for v in doc['broken'])]:
        if len({r['frame'] for r in rows}) != len(rows):
            raise CalibrationError('duplicate proof frame')
        if any(r['frameSha256'] in selection_hashes for r in rows):
            raise CalibrationError('proof pixels were used for prompt selection')
    for rows in [*(c['rows'] for c in doc['candidates']), doc['clean'], *(v['rows'] for v in doc['broken'])]:
        if len({r['frame'] for r in rows}) != len(rows):
            raise CalibrationError('duplicate calibration frame')
        for row in rows:
            for box in [row['expectedBox'], *(d['box'] for d in row['detections'])]:
                if box is not None and (box[0] >= box[2] or box[1] >= box[3]):
                    raise CalibrationError('box has no positive area')
            if row['error'] is not None and row['detections']:
                raise CalibrationError('a gap cannot also be a pixel answer')
    result = _derived(doc)
    if result != (doc['selected'], doc['enabled'], doc['why'], doc['missed']):
        raise CalibrationError('calibration result disagrees with recorded pixel answers')


def read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise CalibrationError('calibration must be a bounded, ordinary file')
    try:
        doc = strict_loads(path.read_text())
    except (ValueError, OSError) as exc:
        raise CalibrationError('calibration cannot be read as strict JSON') from exc
    check(doc)
    return doc


def write(path, doc):
    check(doc)
    encoded = json.dumps(doc, indent=2, allow_nan=False)+'\n'
    if len(encoded.encode()) > MAX_BYTES:
        raise CalibrationError('calibration exceeds its byte cap')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded)
    return path


def calibrate(*, adapter, candidates, selection, clean, broken, game, textures):
    """One loop for any explicit adapter. Frames contain PNG, measured engine box and replay digest.

    Adapters must never learn from ``clean``/``broken``. All four patches and proof frames are
    supplied before selection. No retries, live client, model default or approval path exists.
    """
    def collect(prompt, frames):
        rows = []
        for frame in frames:
            row = {k: copy.deepcopy(frame[k]) for k in ('frame', 'expectedBox', 'replaySha256')}
            row['frameSha256'] = hashlib.sha256(Path(frame['png']).read_bytes()).hexdigest()
            try:
                row.update(detections=copy.deepcopy(adapter.detect(prompt, frame)), error=None)
            except NoAnswer as exc:
                row.update(detections=[], error=str(exc)[:300] or 'observer unavailable')
            rows.append(row)
        return rows
    art = art_digests(game, textures)
    doc = dict(format=FORMAT, machineWritten=True, observer=copy.deepcopy(adapter.describe()),
               art=art, artSha256=digest(art), minimumFloor=adapter.minimum_floor,
               candidates=[], selected=None, clean=[], broken=[], enabled=False, why=[], missed=[])
    for prompt in candidates:
        rows = collect(prompt, selection)
        doc['candidates'].append(dict(prompt=prompt, floor=_floor(rows, adapter.minimum_floor), rows=rows))
    selected, _, _, _ = _derived(doc)
    if selected is not None:
        doc['clean'] = collect(selected, clean)
    # No selected prompt: still name all four copies as unproved, without querying them.
    doc['broken'] = [dict(name=v['name'], patchSha256=v['patchSha256'],
                          rows=collect(selected, v['frames']) if selected is not None else []) for v in broken]
    doc['selected'], doc['enabled'], doc['why'], doc['missed'] = _derived(doc)
    if art_digests(game, textures) != art:
        raise CalibrationError('textures changed during calibration')
    check(doc)
    return doc


class CalibratedObserver:
    """Opt-in gate wrapper. A stale/disabled/different observer yields NoAnswer → needs-review.

    Only use records with independent proof (``recorded-sam`` or ``no-model``); stand-ins can
    exercise calibration but can never enable this verification wrapper.
    """
    def __init__(self, inner, calibration, game):
        check(calibration)
        self.inner, self.record, self.game = inner, copy.deepcopy(calibration), Path(game)

    def _ready(self):
        doc = self.record
        if doc['observer']['evidence'] == 'stand-in':
            raise NoAnswer('stand-in calibration is plumbing proof, not vision evidence')
        if not doc['enabled']:
            raise NoAnswer('visual observer is not calibrated: '+'; '.join(doc['why']))
        try:
            current = art_digests(self.game, doc['art'])
        except (OSError, CalibrationError) as exc:
            raise NoAnswer(f'calibration is stale: {exc}') from exc
        if current != doc['art']:
            raise NoAnswer('calibration is stale: texture digest changed')
        if self.inner.describe() != doc['observer']['identity']:
            raise NoAnswer('calibration belongs to another observer/version')
        source = getattr(self.inner, 'bank', None)
        if source is None:
            source = getattr(getattr(self.inner, 'client', None), 'recording', None)
        if source is None or digest(source) != doc['observer']['sourceSha256']:
            raise NoAnswer('calibration belongs to another recording or template bank')

    def describe(self):
        self._ready()
        return self.inner.describe()

    def segmenter(self):
        self._ready()
        return self.inner.segmenter()

    def look(self, spec, run, *, keep=True):
        self._ready()
        if self.record['observer']['evidence'] == 'recorded-sam' and spec.get('objects', {}).get('player', {}).get('prompt') != self.record['selected']:
            raise NoAnswer('check asks for a different calibrated player prompt')
        seen = copy.deepcopy(self.inner.look(spec, run, keep=keep))
        floor = next(c['floor'] for c in self.record['candidates'] if c['prompt'] == self.record['selected'])
        for frame in seen.get('frames', []):
            objects = frame.get('objects', {})
            if 'player' in objects:
                objects['player'] = [d for d in objects['player'] if d.get('score', 0) >= floor]
        return seen
