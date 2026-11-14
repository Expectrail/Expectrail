"""Opt-in, local template sensor (#262). No model, network, or default-verdict wiring.

Calibration takes a separately pinned clean replay. Observation only reads its frozen bank.
Boxes locate the calibrated rectangle, not a segmentation of the whole sprite. See docs/template-sensor.md.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import math
import re
import time
from pathlib import Path

from expectrail.contracts import digest
from expectrail.gate.record import errors
from expectrail.gate.verify import NoAnswer
from expectrail import resources

ALGORITHM = 'expectrail.template-ncc/v2'
COORDINATES = 'captured-frame pixels; origin top-left; xyxy half-open; y down'
DEFAULTS = dict(algorithm=ALGORITHM, coordinates=COORDINATES, matchThreshold=0.9, agreementIoU=0.5,
                searchMarginPx=16, scales=[0.75, 1.0, 1.25], stridePx=1, sampleSide=16, minimumContrast=8.0)
CAPABILITIES = ['presence', 'position', 'shape']
LIMITATIONS = ['Colour is discarded (luminance matching).', 'No text, semantic identity, or animation correctness.',
               'Normalized correlation ignores uniform brightness/contrast changes; sampling loses fine detail.',
               'No segmentation: boxes locate the calibrated crop, which may include background.',
               'No rotation, nonuniform scale, or partial-occlusion invariance.',
               'Search is local to the engine prediction; an object outside it is not located.',
               'Similar art or background can match; scores are similarity, not probabilities.']
SUPPORTED = {'visible', 'never-crosses', 'inside-region', 'reaches'}
MAX_BANK_BYTES = 64_000_000


class SensorError(ValueError):
    """Invalid calibration or evidence; never a negative pixel detection."""


def imaging():
    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError as exc:
        raise SensorError('template sensor needs Pillow: install Pillow; no model is used') from exc
    return Image, ImageChops, ImageStat


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(doc, kind):
    try:
        json.dumps(doc, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise SensorError('non-finite or non-JSON observation data') from exc
    schema = json.loads((resources.ROOT / 'contracts' / f'{kind}.schema.json').read_text())
    found = errors(doc, schema)
    if found:
        raise SensorError(f'{kind}: {found[0]}')


def frame_files(folder):
    found = {}
    for path in sorted(Path(folder).glob('f*.png')):
        m = re.fullmatch(r'f(\d+)\.png', path.name)
        if m:
            n = int(m[1])
            if n in found:
                raise SensorError(f'duplicate captured frame {n}')
            found[n] = path
    return found


def finite_box(box):
    return (isinstance(box, (list, tuple)) and len(box) == 4
            and all(type(x) in (int, float) and math.isfinite(x) for x in box)
            and box[0] < box[2] and box[1] < box[3])


def player_predictions(trace, frames, fps=60):
    """The body's own world box, using all four corners and the next tick's camera (#259).

    No bundled-game dimensions or inferred visibility. A collision box predicts a region, not
    proof that a sprite was drawn. Missing rows/cameras remain unknown.
    """
    tps = trace.get('physicsTicksPerSecond')
    if type(tps) is not int or type(fps) is not int or fps <= 0 or tps < fps or tps % fps:
        raise SensorError('capture fps must divide the recorded physics tick rate')
    rows = trace.get('rows', [])
    by_tick = {r['tick']: r for r in rows}
    if len(by_tick) != len(rows):
        raise SensorError('duplicate trace ticks')
    step = tps // fps
    out = {}
    for frame in frames:
        tick = (frame + 1) * step - 1
        row = by_tick.get(tick, {})
        later = by_tick.get(tick + 1, row if tick == trace.get('ticks', len(rows)) - 1 else {})
        view, body = later.get('view'), row.get('body')
        box = None
        if finite_box(body) and isinstance(view, list) and len(view) == 6 and all(
                type(x) in (int, float) and math.isfinite(x) for x in view):
            points = [(view[0]*x + view[2]*y + view[4], view[1]*x + view[3]*y + view[5])
                      for x in (body[0], body[2]) for y in (body[1], body[3])]
            box = [min(x for x, y in points), min(y for x, y in points),
                   max(x for x, y in points), max(y for x, y in points)]
            if not finite_box(box):
                box = None
        out[frame] = {'player': box}
    return out


def _image(path):
    Image, _, _ = imaging()
    with Image.open(path) as image:
        if image.format != 'PNG' or image.width * image.height > 16_777_216:
            raise SensorError('expected a PNG no larger than 16 megapixels')
        return image.convert('L')


def _contrast(image):
    _, _, ImageStat = imaging()
    return ImageStat.Stat(image).stddev[0]


def load_bank(path_or_doc):
    if isinstance(path_or_doc, dict):
        bank = copy.deepcopy(path_or_doc)
    else:
        data = Path(path_or_doc).read_bytes()
        if len(data) > MAX_BANK_BYTES:
            raise SensorError('template bank is too large')
        bank = json.loads(data)
    validate(bank, 'template-bank')
    if bank['config']['matchThreshold'] <= 0 or bank['config']['agreementIoU'] <= 0:
        raise SensorError('match and agreement thresholds must be greater than zero')
    Image, _, _ = imaging()
    for item in bank['templates']:
        try:
            pixels = base64.b64decode(item['pixels'], validate=True)
        except ValueError as exc:
            raise SensorError('invalid template pixels') from exc
        if len(pixels) != item['width'] * item['height'] or hashlib.sha256(pixels).hexdigest() != item['pixelsSha256']:
            raise SensorError('template pixel length or digest does not match')
        if not finite_box(item['box']) or not finite_box(item['predictedBox']):
            raise SensorError('invalid calibration box')
        image = Image.frombytes('L', (item['width'], item['height']), pixels)
        sample = image.resize((bank['config']['sampleSide'],)*2, Image.Resampling.BOX)
        if min(_contrast(image), _contrast(sample)) < bank['config']['minimumContrast']:
            raise SensorError('flat template cannot identify a sprite')
    return bank


def calibrate(clean_run, *, clean_tree, frames, out=None, config=None, predicted=None):
    """Capture templates ONLY from a clean replay pinned to a caller-selected trusted game digest.

    patch:null alone is not proof of approval. The caller must obtain clean_tree from its trusted
    clean checkout, never the candidate. No approval is created here. Hashes bind the replay,
    trace and source PNGs; candidate observation has no calibration path.
    """
    root = Path(clean_run)
    replay = json.loads((root / 'replay.json').read_text())
    game = replay['game']
    if game.get('tree') != clean_tree or game.get('patch') is not None or game.get('patchSha256') is not None:
        raise SensorError('calibration needs the pinned clean tree with no candidate patch')
    if sha(root / 'trace.json') != replay['trace']['sha256']:
        raise SensorError('clean trace digest does not match its replay')
    trace = json.loads((root / 'trace.json').read_text())
    files = frame_files(root / 'frames')
    indices = sorted(set(frames))
    if not indices or not all(type(n) is int and n >= 0 for n in indices):
        raise SensorError('select at least one clean frame')
    boxes = predicted if predicted is not None else player_predictions(trace, indices, replay['capture']['fps'])
    bank = {'format': 'expectrail.template-bank/v0', 'config': dict(DEFAULTS, **(config or {})),
            'clean': {'gameTree': clean_tree, 'replaySha256': sha(root / 'replay.json'),
                      'traceSha256': replay['trace']['sha256']}, 'templates': []}
    for n in indices:
        if n not in files or n >= len(replay['frameSha256']) or sha(files[n]) != replay['frameSha256'][n]:
            raise SensorError(f'clean frame {n} is missing or does not match its replay')
        image = _image(files[n])
        for name, box in boxes.get(n, {}).items():
            if not finite_box(box):
                raise SensorError(f'clean frame {n}: {name} has no measured box')
            crop = [math.floor(box[0]), math.floor(box[1]), math.ceil(box[2]), math.ceil(box[3])]
            if crop[0] < 0 or crop[1] < 0 or crop[2] > image.width or crop[3] > image.height:
                raise SensorError('calibration crop must be entirely on screen')
            patch = image.crop(crop)
            pixels = patch.tobytes()
            bank['templates'].append(dict(object=name, frame=n, frameSha256=sha(files[n]), box=crop,
                predictedBox=list(box),
                sourceReplaySha256=bank['clean']['replaySha256'], mirrorX=False,
                width=patch.width, height=patch.height, pixels=base64.b64encode(pixels).decode(),
                pixelsSha256=hashlib.sha256(pixels).hexdigest()))
    bank['sources'] = [bank['clean']]
    bank['calibration'] = dict(selection='explicit-frames', selectionSimilarity=1.0, sourceFrames=len(indices),
        eligibleFrames=len(bank['templates']), mirrored=False, thresholdFloor=bank['config']['matchThreshold'],
        thresholdSelected=bank['config']['matchThreshold'], validationReplaySha256=None,
        positives=0, negatives=0, positiveMatches=0, negativeMatches=0, status='not-run')
    bank = load_bank(bank)
    if out is not None:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Never overwrite a calibrated bank during a candidate run, or silently recalibrate it.
        with path.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(bank, indent=2) + '\n')
    return bank


def _iou(a, b):
    area = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - area
    return area / union if union > 0 else 0.0


def _pooled(array, side):
    """Integer area bins, repeated nearest cells when upsampling. Shared by bank and search."""
    import numpy as np
    height, width = array.shape
    xs = np.floor(np.arange(side)*width/side).astype(int)
    xe = np.maximum(xs+1, np.floor(np.arange(1,side+1)*width/side).astype(int))
    ys = np.floor(np.arange(side)*height/side).astype(int)
    ye = np.maximum(ys+1, np.floor(np.arange(1,side+1)*height/side).astype(int))
    integral = np.pad(np.asarray(array, dtype=np.float64).cumsum(0).cumsum(1), ((1,0),(1,0)))
    values = (integral[ye[:,None],xe] - integral[ys[:,None],xe]
              - integral[ye[:,None],xs] + integral[ys[:,None],xs])
    return (values/((ye-ys)[:,None]*(xe-xs))).astype(np.float32).ravel()


def _feature(item, side):
    import numpy as np
    array = np.frombuffer(base64.b64decode(item['pixels']),dtype=np.uint8).reshape(item['height'],item['width'])
    vector = _pooled(array,side)
    vector -= vector.mean()
    norm = float(np.sqrt(np.dot(vector,vector)))
    return vector/max(norm,1e-12)


class Matcher:
    """NumPy exhaustive region search, batched by output size; no per-position Python matching.

    Integer-area pooling and float32 NCC are versioned as v2. Float64 summed-area images avoid
    cancellation on large captures. einsum uses no threaded BLAS or process-global thread knobs.
    """
    def __init__(self, templates, config):
        import numpy as np
        self.templates, self.config = templates, config
        self.features = np.stack([_feature(t,config['sampleSide']) for t in templates])

    def match(self, image, predicted):
        import numpy as np
        config = self.config
        margin = config['searchMarginPx']
        roi = [max(0,math.floor(predicted[0])-margin),max(0,math.floor(predicted[1])-margin),
               min(image.width,math.ceil(predicted[2])+margin),min(image.height,math.ceil(predicted[3])+margin)]
        array = np.asarray(image.crop(roi),dtype=np.float64)
        integral = np.pad(array.cumsum(0).cumsum(1),((1,0),(1,0)))
        groups = {}
        for index,item in enumerate(self.templates):
            original = item['predictedBox']
            ratio = min((predicted[2]-predicted[0])/(original[2]-original[0]),
                        (predicted[3]-predicted[1])/(original[3]-original[1]))
            for order,factor in enumerate(config['scales']):
                scale = ratio*factor
                size = (max(4,round(item['width']*scale)),max(4,round(item['height']*scale)))
                groups.setdefault(size,[]).append((index,order,scale))
        best, best_key = None, None
        side = config['sampleSide']
        for (width,height),entries in groups.items():
            xmax,ymax = array.shape[1]-width,array.shape[0]-height
            if xmax<0 or ymax<0:
                continue
            xs = np.floor(np.arange(side)*width/side).astype(int)
            xe = np.maximum(xs+1,np.floor(np.arange(1,side+1)*width/side).astype(int))
            ys = np.floor(np.arange(side)*height/side).astype(int)
            ye = np.maximum(ys+1,np.floor(np.arange(1,side+1)*height/side).astype(int))
            xa,ya = np.meshgrid(xs,ys);xb,yb = np.meshgrid(xe,ye)
            xa,ya,xb,yb = [a.ravel() for a in (xa,ya,xb,yb)]
            areas = (xb-xa)*(yb-ya)
            tx = self.features[[e[0] for e in entries]]
            count = (xmax+1)*(ymax+1)
            # Bounded allocation even for large regions/banks. All positions are searched.
            for start in range(0,count,512):
                ids = np.arange(start,min(count,start+512))
                x = (ids%(xmax+1))[:,None];y = (ids//(xmax+1))[:,None]
                samples = ((integral[y+yb,x+xb]-integral[y+ya,x+xb]
                            -integral[y+yb,x+xa]+integral[y+ya,x+xa])/areas).astype(np.float32)
                samples -= samples.mean(axis=1,keepdims=True)
                norms = np.sqrt(np.einsum('ij,ij->i',samples,samples))
                valid = norms >= side*config['minimumContrast']
                samples /= np.maximum(norms[:,None],1e-12)
                scores = np.clip(samples @ tx.T,0,1)
                scores[~valid] = 0
                # Explicit tie ordering: source template, scale, y, x; independent of batching.
                value = float(scores.max())
                for pos,col in np.argwhere(scores == value)[:1] if value == 0 else np.argwhere(scores == value):
                    index,order,scale = entries[int(col)]
                    px,py = int(x[pos,0])+roi[0],int(y[pos,0])+roi[1]
                    key = (-round(value,7),index,order,py,px)
                    if best_key is None or key < best_key:
                        best_key = key
                        best = dict(box=[px,py,px+width,py+height],score=value,
                                    templateFrame=self.templates[index]['frame'],scale=scale)
        return best,roi


def match(image, templates, predicted, config):
    return Matcher(templates,config).match(image,predicted)


def calibrate_routes(clean_runs, validation_run, *, clean_tree, config=None, similarity=0.985):
    """Select diverse crops from EVERY eligible clean training frame, with mirrored partners.

    No measured/candidate input is accepted by this API. Threshold selection uses a separate
    clean validation route and off-player regions only; it may raise, never lower, the 0.90 floor.
    A failed calibration target is recorded, not hidden by lowering the threshold.
    """
    import numpy as np
    Image, _, _ = imaging()
    settings = dict(DEFAULTS, **(config or {}))
    if settings['matchThreshold'] < 0.9:
        raise SensorError('calibration cannot lower the 0.90 threshold floor')
    selected, features, sources = [], [], []
    source_frames = eligible_frames = 0
    bank = None
    for root in map(Path,clean_runs):
        record = json.loads((root/'replay.json').read_text())
        trace = json.loads((root/'trace.json').read_text())
        files = frame_files(root/'frames')
        predictions = player_predictions(trace,files,record['capture']['fps'])
        eligible = []
        for n,path in files.items():
            source_frames += 1
            image = _image(path)
            box = predictions[n]['player']
            if not finite_box(box) or box[0]<0 or box[1]<0 or box[2]>image.width or box[3]>image.height:
                continue
            crop = image.crop((math.floor(box[0]),math.floor(box[1]),math.ceil(box[2]),math.ceil(box[3])))
            sample = _pooled(np.asarray(crop),settings['sampleSide'])
            if min(_contrast(crop),float(sample.std())) >= settings['minimumContrast']:
                eligible.append(n)
        if not eligible:
            raise SensorError(f'no usable clean calibration frames in {root.name}')
        candidate = calibrate(root,clean_tree=clean_tree,frames=eligible,config=settings)
        sources.append(candidate['clean'])
        eligible_frames += len(eligible)
        bank = bank or candidate
        for item in candidate['templates']:
            feature = _feature(item,settings['sampleSide'])
            if features and float(np.einsum('ij,j->i',np.asarray(features),feature).max()) >= similarity:
                continue
            mirrored = copy.deepcopy(item)
            pixels = np.frombuffer(base64.b64decode(item['pixels']),dtype=np.uint8).reshape(item['height'],item['width'])[:,::-1].tobytes()
            mirrored.update(pixels=base64.b64encode(pixels).decode(),pixelsSha256=hashlib.sha256(pixels).hexdigest(),mirrorX=True)
            selected.extend((item,mirrored))
            features.extend((feature,_feature(mirrored,settings['sampleSide'])))
            if len(selected)>2048:
                raise SensorError('clean animation coverage needs more than 2048 templates; no measured run was used')
    if bank is None:
        raise SensorError('at least one clean training route is required')
    bank['templates'],bank['sources'] = selected,sources
    bank['calibration'].update(selection='all-clean-crops',selectionSimilarity=similarity,
                               sourceFrames=source_frames,eligibleFrames=eligible_frames,mirrored=True)
    bank = load_bank(bank)
    root = Path(validation_run)
    replay = json.loads((root/'replay.json').read_text())
    if (replay['game']['tree'] != clean_tree or replay['game'].get('patch') is not None
            or replay['game'].get('patchSha256') is not None or sha(root/'trace.json') != replay['trace']['sha256']):
        raise SensorError('threshold calibration requires a pinned unpatched clean validation replay')
    if sha(root/'replay.json') in {s['replaySha256'] for s in sources}:
        raise SensorError('threshold validation must be a separate clean replay')
    trace = json.loads((root/'trace.json').read_text())
    files = frame_files(root/'frames')
    predictions = player_predictions(trace,files,replay['capture']['fps'])
    matcher = Matcher(selected,settings)
    positives,negatives = [],[]
    for n,path in files.items():
        if n>=len(replay['frameSha256']) or sha(path)!=replay['frameSha256'][n]:
            raise SensorError('validation pixels do not match the clean replay')
        image,box = _image(path),predictions[n]['player']
        if not finite_box(box) or box[0]<0 or box[1]<0 or box[2]>image.width or box[3]>image.height:
            continue
        found,_ = matcher.match(image,box)
        positives.append(found['score'] if found and _iou(found['box'],box)>=settings['agreementIoU'] else 0)
        width = box[2]-box[0]
        distance = width+2*settings['searchMarginPx']+8
        for direction in (1,-1):
            negative = [box[0]+direction*distance,box[1],box[2]+direction*distance,box[3]]
            if negative[0]>=0 and negative[2]<=image.width:
                found,_ = matcher.match(image,negative)
                negatives.append(found['score'] if found else 0)
                break
    floor = settings['matchThreshold']
    choices = sorted({floor} | {n/100 for n in range(math.ceil(floor*100),101)})
    chosen,status = floor,'unmet'
    for threshold in choices:
        if (positives and negatives and sum(s>=threshold for s in positives)/len(positives)>=0.95
                and sum(s>=threshold for s in negatives)/len(negatives)<=0.01):
            chosen,status = threshold,'met'
            break
    bank['config']['matchThreshold'] = chosen
    bank['sources'].append(dict(gameTree=clean_tree,replaySha256=sha(root/'replay.json'),traceSha256=replay['trace']['sha256']))
    bank['calibration'].update(thresholdFloor=floor,thresholdSelected=chosen,
        validationReplaySha256=sha(root/'replay.json'),positives=len(positives),negatives=len(negatives),
        positiveMatches=sum(s>=chosen for s in positives),negativeMatches=sum(s>=chosen for s in negatives),status=status)
    return load_bank(bank)


def from_replay(trace, *, replay_sha256, frames_dir, bank, spec, fps=60, predicted=None, agreeing=None, completed=None, on_frame=None):
    """Observation document plus per-object measurement reasons; same agreeing callback shape as SAM.

    Unavailable frames are explicitly marked. TemplateObserver.look refuses to certify a spec
    over any of them. Low-score or displaced matches are negative pixel evidence, not outages.
    """
    bank = load_bank(bank)
    config = bank['config']
    names = list(spec['objects'])
    by_name = {name: [t for t in bank['templates'] if t['object'] == name] for name in names}
    if not names or any(not items for items in by_name.values()):
        raise SensorError('every requested object needs a clean template; no engine-only object is invented')
    matchers = {name: Matcher(items,config) for name,items in by_name.items()}
    if on_frame is not None and agreeing is not None:
        raise SensorError('frame checkpoints require the built-in agreement rule')
    files = frame_files(frames_dir)
    tps = trace.get('physicsTicksPerSecond')
    if type(tps) is not int or type(fps) is not int or fps <= 0 or tps < fps or tps % fps:
        raise SensorError('capture fps must divide the recorded physics tick rate')
    count = trace.get('ticks', 0) // (tps // fps)
    lo, hi = spec.get('window', {}).get('fromFrame', 0), spec.get('window', {}).get('toFrame', count-1)
    indices = list(range(lo, min(hi, count-1)+1))
    boxes = predicted if predicted is not None else player_predictions(trace, indices, fps)
    frames = []
    for n in indices:
        if completed is not None and n in completed:
            frames.append(copy.deepcopy(completed[n]))
            continue
        started = time.perf_counter()
        image, error = None, None
        try:
            image = _image(files[n])
        except (KeyError, OSError, ValueError) as exc:
            error = f'frame unavailable ({type(exc).__name__})'
        objects, evidence = {}, {}
        for name in names:
            box = boxes.get(n, {}).get(name)
            row = dict(status='unavailable', reason=error or 'engine has no measured search box',
                       predictedBox=box if finite_box(box) else None, searchBox=None, rawBox=None,
                       score=None, templateFrame=None, scale=None)
            objects[name] = []
            if image is not None and finite_box(box):
                if box[0] < 0 or box[1] < 0 or box[2] > image.width or box[3] > image.height:
                    row.update(status='out-of-frame', reason='predicted crop is not entirely on screen')
                else:
                    found, roi = matchers[name].match(image, box)
                    row['searchBox'] = roi
                    if found:
                        row.update(rawBox=found['box'], score=round(found['score'], 6),
                                   templateFrame=found['templateFrame'], scale=round(found['scale'], 6))
                    if found is None or found['score'] < config['matchThreshold']:
                        row.update(status='not-found', reason='no template reached the pixel similarity threshold')
                    elif _iou(found['box'], box) < config['agreementIoU']:
                        row.update(status='displaced', reason='pixel match does not overlap the engine prediction enough')
                    else:
                        row.update(status='matched', reason='pixels match the clean template inside the predicted region')
                        objects[name] = [dict(box=found['box'], score=round(found['score'], 6))]
            evidence[name] = row
        frame = dict(frame=n, objects=objects, sensor=evidence)
        frames.append(frame)
        if on_frame is not None:
            on_frame(copy.deepcopy(frame), time.perf_counter()-started)
    if agreeing is not None:
        original = {f['frame']: copy.deepcopy(f['objects']) for f in frames}
        filtered = agreeing(copy.deepcopy(original))
        for f in frames:
            for name in names:
                kept = filtered.get(f['frame'], {}).get(name, [])
                if any(d not in original[f['frame']][name] for d in kept):
                    raise SensorError('agreeing may only remove detections')
                if f['objects'][name] and not kept:
                    f['sensor'][name].update(status='displaced', reason='the supplied agreeing filter removed the pixel match')
                f['objects'][name] = kept
    doc = {'format': 'expectrail.observations/v0', 'replay': {'sha256': replay_sha256},
           'model': {'name': ALGORITHM, 'prompts': {n: spec['objects'][n].get('prompt', n) for n in names},
                     'sensor': dict(config=config, bankSha256=digest(bank), clean=bank['clean'],
                                    capabilities=CAPABILITIES, limitations=LIMITATIONS,
                                    sources=bank['sources'], calibration=bank['calibration'],
                                    captureFps=fps, physicsTicksPerSecond=tps)}, 'frames': frames}
    validate(doc, 'observations')
    return doc


def summarize(doc):
    """Counts and denominators, not a product verdict. No measurements => null rates, never 100%."""
    validate(doc, 'observations')
    if 'sensor' not in doc.get('model', {}):
        raise SensorError('not a template sensor observation')
    indices = [f['frame'] for f in doc['frames']]
    if len(set(indices)) != len(indices):
        raise SensorError('duplicate observation frames')
    for frame in doc['frames']:
        if 'sensor' not in frame or set(frame['sensor']) != set(frame['objects']):
            raise SensorError('every observed object needs sensor evidence')
        for name, row in frame['sensor'].items():
            expected = [dict(box=row['rawBox'], score=row['score'])] if row['status'] == 'matched' else []
            if frame['objects'][name] != expected:
                raise SensorError('detections disagree with the sensor evidence')
    rows = [(f['frame'], name, row) for f in doc['frames'] for name, row in f['sensor'].items()]
    counts = {state: sum(r['status'] == state for _, _, r in rows)
              for state in ('matched', 'not-found', 'displaced', 'unavailable', 'out-of-frame')}
    measured = counts['matched'] + counts['not-found'] + counts['displaced']
    alarms = counts['not-found'] + counts['displaced']
    return dict(frames=len(doc['frames']), objectFrames=len(rows), measured=measured, counts=counts,
                agreementRate=counts['matched']/measured if measured else None,
                alarmRate=alarms/measured if measured else None,
                disagreements=[dict(frame=f, object=n, **r) for f, n, r in rows if r['status'] != 'matched'])


class TemplateObserver:
    """Explicit observer-interface adapter. No default gate or model adapter is changed."""
    def __init__(self, bank, *, fps=60, predicted=None, agreeing=None, required_capabilities=()):
        self.bank = load_bank(bank)
        self.fps, self.predicted, self.agreeing = fps, predicted, agreeing
        self.required = set(required_capabilities)

    def describe(self):
        return {'name': 'template', 'provider': 'local', 'model': ALGORITHM}

    def look(self, spec, run, *, keep=True):
        del keep  # no candidate cache, persistence, training or calibration
        if self.required - set(CAPABILITIES) or spec.get('assertion', {}).get('type') not in SUPPORTED:
            raise NoAnswer('template sensor cannot certify the requested distinction (colour/text/identity are unsupported)')
        try:
            doc = from_replay(run['trace'], replay_sha256=run['replaySha256'], frames_dir=run['framesDir'],
                              bank=self.bank, spec=spec, fps=self.fps, predicted=self.predicted, agreeing=self.agreeing)
            summary = summarize(doc)
            if not summary['measured'] or summary['counts']['unavailable'] or summary['counts']['out-of-frame']:
                raise SensorError('not all requested frames have readable pixels and an on-screen measured search box')
            return doc
        except (SensorError, OSError, KeyError, TypeError) as exc:
            raise NoAnswer(f'template sensor could not observe: {exc}') from exc


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest='command', required=True)
    cal = sub.add_parser('calibrate')
    cal.add_argument('--clean-run', type=Path, required=True)
    cal.add_argument('--clean-tree', required=True, help='digest from a separately trusted clean checkout')
    cal.add_argument('--frames', required=True, help='comma-separated clean frame numbers selected by the operator')
    cal.add_argument('--out', type=Path, required=True)
    obs = sub.add_parser('observe')
    obs.add_argument('--run', type=Path, required=True)
    obs.add_argument('--bank', type=Path, required=True)
    obs.add_argument('--spec', type=Path, required=True)
    obs.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.command == 'calibrate':
            calibrate(args.clean_run, clean_tree=args.clean_tree, frames=[int(n) for n in args.frames.split(',')], out=args.out)
            print(f'Captured clean templates in {args.out}; no candidate was read.')
        else:
            replay = json.loads((args.run/'replay.json').read_text())
            doc = from_replay(json.loads((args.run/'trace.json').read_text()), replay_sha256=sha(args.run/'replay.json'),
                              frames_dir=args.run/'frames', bank=args.bank, spec=json.loads(args.spec.read_text()),
                              fps=replay['capture']['fps'])
            args.out.write_text(json.dumps(doc, indent=2)+'\n')
            result = summarize(doc)
            print(json.dumps(result, indent=2))
            return 0 if result['measured'] and not result['disagreements'] else 2
    except (SensorError, OSError, ValueError, KeyError) as exc:
        p.exit(2, f'template sensor: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
