"""Offline measured onboarding review and the explicit human answers reader (#331)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from expectrail import approval, onboarding, project_config, viewer
from expectrail.contracts import load_strict, strict_loads, validate, validate_v1
from expectrail.evaluator import evaluate
from expectrail.gate.record import read_bytes_capped

MAX_PAGE_BYTES = 120 * 1024
MAX_IMAGE_BYTES = 12 * 1024
MAX_NATIVE_ART_BYTES = 16 * 1024


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def local(root, name, *, exists=True):
    name = str(name)
    rel = Path(name)
    if rel.is_absolute() or not rel.parts or '..' in rel.parts:
        raise ValueError('A review path must stay inside its project.')
    path = root / rel
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.resolve().is_relative_to(root):
        raise ValueError('A review input or destination is a symbolic link or leaves its project.')
    if (exists or path.exists()) and not path.is_file():
        raise ValueError(f'Review input is missing: {name}')
    return path


def read(path, cap=4 * 1024 * 1024):
    return read_bytes_capped(Path(path), cap, Path(path).name)


def encoded(doc):
    return (json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()


def png_size(data):
    if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data) < 24:
        raise ValueError('A frame is not a PNG image.')
    width, height = struct.unpack('>II', data[16:24])
    if not (0 < width <= 16384 and 0 < height <= 16384):
        raise ValueError('A frame has invalid dimensions.')
    return width, height


def thumbnail(path, *, crop=None, side=240):
    """A few small raster previews; no image package is imported at module load."""
    data = read(path, 16 * 1024 * 1024)
    if crop is None and data.startswith(b'\x89PNG\r\n\x1a\n'):
        width, height = png_size(data)
        if max(width, height) <= side and len(data) <= MAX_IMAGE_BYTES:
            return data, (width, height)
    try:
        import io
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(Path(path)) as source:
            image = source.convert('RGB')
            if crop is not None:
                image = image.crop(tuple(int(v) for v in crop))
            image.thumbnail((side, side))
            for size in (side, 160, 112):
                image.thumbnail((size, size))
                out = io.BytesIO(); image.quantize(colors=64).save(out, format='PNG', optimize=True)
                if len(out.getvalue()) <= MAX_IMAGE_BYTES:
                    return out.getvalue(), image.size
    except (OSError, ValueError):
        return None
    return None


def webp_size(data):
    """Read a bounded WebP canvas header; the browser decodes the original art, not Python."""
    if (len(data) < 30 or data[:4] != b'RIFF' or data[8:12] != b'WEBP'
            or int.from_bytes(data[4:8], 'little') + 8 != len(data)):
        return None
    kind = data[12:16]
    length = int.from_bytes(data[16:20], 'little')
    if 20 + length > len(data):
        return None
    if kind == b'VP8L' and length >= 5 and data[20] == 0x2f:
        bits = int.from_bytes(data[21:25], 'little')
        if bits >> 29:
            return None
        size = ((bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1)
    elif kind == b'VP8 ' and length >= 10 and not data[20] & 1 and data[23:26] == b'\x9d\x01\x2a':
        size = (int.from_bytes(data[26:28], 'little') & 0x3fff,
                int.from_bytes(data[28:30], 'little') & 0x3fff)
    elif kind == b'VP8X' and length >= 10 and data[21:24] == b'\0\0\0':
        size = (int.from_bytes(data[24:27], 'little') + 1, int.from_bytes(data[27:30], 'little') + 1)
    else:
        return None
    return size if all(0 < n <= 4096 for n in size) else None


def native_sprite(state, path):
    """A small original WebP can be embedded without an optional image decoder.

    This is a sprite preview only. It never invents a measured frame/crop or makes an
    unmeasured object reviewable. PNG thumbnails keep their existing byte budget.
    """
    try:
        data = read(path, MAX_NATIVE_ART_BYTES)
    except (OSError, ValueError):
        return None
    size = webp_size(data)
    if size is None:
        return None
    name = f'sprites/{sha(data)}.webp'
    dest = state / name; dest.parent.mkdir(exist_ok=True); dest.write_bytes(data)
    return {'path': name, 'sha256': sha(data), 'size': list(size), 'frame': 0, 'mime': 'image/webp'}


def native_sprite_bytes(state, frame):
    """Read only the unchanged, bounded original art saved for this review."""
    try:
        path = local(Path(state).resolve(), frame['path'])
        data = read(path, MAX_NATIVE_ART_BYTES)
        if (frame.get('mime') == 'image/webp' and sha(data) == frame.get('sha256')
                and webp_size(data) == tuple(frame.get('size') or ())):
            return data
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def asset(state, data, size, frame):
    name = f'frames/after-onboard-{sha(data)[:16]}-{frame:08d}.png'
    path = state / name; path.parent.mkdir(exist_ok=True); path.write_bytes(data)
    return {'path': name, 'sha256': sha(data), 'frame': frame, 'size': list(size)}


def select_three(frames):
    values = sorted(frames)
    if len(values) < 3:
        return values
    return [values[0], values[len(values) // 2], values[-1]]


def capture_data(folder):
    folder = Path(folder).resolve()
    trace = strict_loads(read(folder / 'trace.json').decode())
    replay = strict_loads(read(folder / 'replay.json').decode())
    fps = int(replay['capture']['fps'])
    from agents.observations import from_trace_synthetic
    # Older configured traces store a logical viewport although role boxes are in
    # captured pixels. The page uses the PNG's actual dimensions for visibility;
    # it never rewrites the trace or changes the gate's observation policy.
    measured = trace
    first_png = folder / 'frames' / 'f00000000.png'
    if trace.get('bindings') and first_png.is_file():
        measured = {**trace, 'viewport': list(png_size(read(first_png, 16 * 1024 * 1024)))}
    obs = from_trace_synthetic(measured, replay_sha256=sha(read(folder / 'replay.json')), fps=fps)
    return {'folder': folder, 'trace': trace, 'replay': replay, 'fps': fps, 'observations': obs}


def check_words(spec):
    a = spec['assertion']; subject = a['object'].replace('_', ' ')
    kind = a['type']; tolerance = a.get('tolerancePx', a.get('boundary', {}).get('tolerancePx', 0))
    if kind == 'inside-region':
        region = a['region']
        where = ('the rectangle ' + ', '.join(str(v) for v in region['box']) + ' (left, top, right, bottom)'
                 if 'box' in region else region['relativeTo'].replace('_', ' ') + "'s box")
        if 'relativeTo' in region and region.get('marginPx',0):
            margin=region['marginPx']
            where += f", {'expanded' if margin>0 else 'shrunk'} by {abs(margin):g} pixels on every edge"
        condition = f'{subject} stays inside {where}, allowing {tolerance:g} pixels.'
        passed, failed = 'The entire object box stays within that region.', 'An edge of the object box leaves the region.'
    elif kind == 'never-crosses':
        b = a['boundary']
        where = (f"{b['relativeTo'].replace('_', ' ')}'s {b['edge']} edge" if 'relativeTo' in b
                 else f"{b['axis']} = {b['value']:g}")
        condition = f"{subject} stays {b['side'].replace('-', ' ')} {where}, allowing {tolerance:g} pixels."
        if 'relativeTo' in b and b.get('requireOverlap',True):
            other='horizontal' if b['side'] in ('above','below') else 'vertical'
            condition += f' Only frames with {other} overlap between the objects are checked.'
        passed, failed = 'Its box stays on the required side.', 'Its box crosses the boundary beyond the allowance.'
    elif kind == 'visible':
        condition = f"{subject} is found in at least {100 * a.get('minFraction',1.0):g}% of the checked frames."
        passed, failed = 'The required fraction is found.', 'Too few checked frames contain the object.'
    else:
        condition = f"{subject} reaches {a['goal'].replace('_', ' ')} within {a.get('distancePx', 0):g} pixels."
        passed, failed = 'The object reaches that goal during the window.', 'It never reaches the goal during the window.'
    w = spec.get('window', {})
    window = f"Frames {w.get('fromFrame', 0)} through {w['toFrame']} inclusive." if 'toFrame' in w else (f"From frame {w['fromFrame']} to the end of the captured route." if w.get('fromFrame') else 'The whole captured route.')
    c = spec.get('coverage', {})
    if c.get('whenPlayerVisible'):window += ' Only while the engine says the player is in play (visible).'
    if c.get('minFrames'):window += f" At least {c['minFrames']} exercised frames are required."
    elif kind=='reaches' or w.get('toFrame')==w.get('fromFrame',0):window += ' At least one exercised frame is required.'
    else:window += ' At least two exercised frames are required (one for a single-frame window).'
    if c.get('minFraction'):window += f" At least {100*c['minFraction']:g}% of the window must be judged as well."
    if c.get('routes'):window += ' Applies only to routes: '+', '.join(c['routes'])+'. Missing route identity is not a pass.'
    for checkpoint in c.get('reached', []):
        if checkpoint.get('type') == 'position-region':
            window += (f" The player must reach world rectangle {', '.join(str(v) for v in checkpoint['box'])} "
                       f"at or after tick {checkpoint.get('fromTick', 0)}; otherwise it is not exercised.")
        elif checkpoint['type']=='on-floor':
            window += f" The player must touch the floor at or after tick {checkpoint.get('fromTick',0)}."
        elif checkpoint['type']=='coin-count-change':
            window += f" The recorded coin count must change at or after tick {checkpoint.get('fromTick',0)}."
        elif checkpoint['type']=='position-at-tick':
            window += (f" At exactly tick {checkpoint['tick']}, {checkpoint['object']} must be within "
                       f"{checkpoint['tolerancePx']:g} pixels of world position ({checkpoint['x']:g}, {checkpoint['y']:g}).")
    return {'sentence': spec['instruction'], 'object': subject, 'condition': condition,
            'window': window, 'pass': passed, 'fail': failed}


def local_godot(explicit=None):
    from harness.run import GODOT_VERSION, tools_dir
    choices = [Path(explicit)] if explicit else [tools_dir() / 'godot' / f'Godot_v{GODOT_VERSION}_linux.x86_64']
    for name in ('godot', 'godot4'):
        found = shutil.which(name)
        if found and not explicit:choices.append(Path(found))
    for path in choices:
        if path.is_file():
            said = subprocess.run([str(path), '--version'], capture_output=True, text=True, timeout=10)
            if said.returncode == 0 and said.stdout.strip().startswith(GODOT_VERSION.replace('-', '.')):
                return path
    if explicit:raise ValueError('The selected engine is not the pinned Godot 4.7.2 build.')
    return None


def prepare(root, state, *, source=None, evidence=None, broken=(), recording=None, godot=None):
    root = root.resolve(); started = now(); t0 = time.monotonic(); stages = []
    source = source or project_config.FILENAME
    inputs = {}
    def input_bytes(name):
        data = read(local(root, name)); inputs[str(name)] = sha(data); return data
    if (root / source).exists():
        raw = input_bytes(source); original = strict_loads(raw.decode())
        config = original if source == project_config.FILENAME else original.get('config')
        if not config:
            raise ValueError('Review requires a complete project config; existing files were preserved.')
        config = project_config.validate(deepcopy(config), root)
        config_hash = sha(raw)
    else:
        proposal = onboarding.proposal(root, onboarding.inspect(root))
        if 'unresolvedBindings' in proposal:
            raise ValueError('No complete binding choice is available; run init and resolve the bindings first.')
        config = proposal['config']; config_hash = None
    input_bytes('project.godot')
    scene = config['entryScene'].removeprefix('res://'); input_bytes(scene)
    generated_route = None
    if not config.get('routes'):
        proposal = onboarding.proposal(root, onboarding.inspect(root))
        generated_route = proposal['route']
        config['routes'] = proposal['config']['routes']
    route_name = config['routes'][0]
    existed = (root / route_name).is_file()
    if existed:
        route_raw = input_bytes(route_name); route_doc = strict_loads(route_raw.decode())
        if Path(route_name).name.startswith('draft-first-') and sha(route_raw)[:16] != Path(route_name).stem.removeprefix('draft-first-'):
            raise ValueError('The saved first route has changed; rerun init or review the route again.')
    else:
        if config_hash is not None and generated_route is None:raise ValueError('The selected first route is missing; restore it or rerun init.')
        proposal = onboarding.proposal(root, onboarding.inspect(root)); route_doc = proposal['route']
        if route_name != proposal['config']['routes'][0]:raise ValueError('The selected first route is missing.')
        route_raw = encoded(route_doc)
    validate(route_doc, 'route')
    specs = []
    names = list(dict.fromkeys([*config.get('approvedContracts', []),
              *[str(p.relative_to(root)) for folder in ('checks', 'specs') if (root / folder).is_dir()
                for p in sorted((root / folder).glob('*.json'))]]))
    for name in names:
        body = strict_loads(read(local(root, name)).decode()); validate(body, 'test-spec')
        bare = {k:v for k,v in body.items() if k != 'approval'}
        problems = approval.lint(bare)
        if problems:raise ValueError('; '.join(problems))
        if any(s['id'] == body['id'] for s in specs):raise ValueError('Two draft checks have the same id.')
        specs.append({'path': name, 'id': body['id'], 'specSha256': approval.spec_sha256(body),
                      'fileSha256': sha(read(local(root, name))), 'objects': list(body['objects']),
                      'approved': approval.approved(body), 'body': body})
    roles = list(dict.fromkeys([*config['bindings'], *[r for s in specs for r in s['objects']]]))
    for binding in config['bindings'].values():
        if binding.get('texture'):input_bytes(binding['texture'].removeprefix('res://'))
    stages.append({'name':'project and first route','status':'completed','seconds':time.monotonic()-t0,'reason':None})
    clean = None; captures = {}; capture_t = time.monotonic()
    if evidence:
        clean = capture_data(evidence)
    else:
        engine = local_godot(godot)
        if engine:
            from harness.run import run
            with tempfile.TemporaryDirectory(prefix='expectrail-onboard-capture-') as temp:
                temp = Path(temp); route_path = temp / 'route.json'; route_path.write_bytes(route_raw)
                try:
                    run(route_path, temp / 'clean', game=root, project=config, godot=engine)
                    # Keep only the source capture until thumbnails have been made below.
                    shutil.copytree(temp / 'clean', state / 'capture', ignore=shutil.ignore_patterns('work','sandbox'))
                    clean = capture_data(state / 'capture')
                except (SystemExit, OSError, ValueError) as exc:
                    stages.append({'name':'clean replay','status':'failed','seconds':time.monotonic()-capture_t,'reason':str(exc)[:300]})
        else:
            stages.append({'name':'clean replay','status':'skipped','seconds':0,'reason':'Pinned Godot is unavailable; no capture was made. Install Godot 4.7.2 or supply --evidence.'})
    if clean:
        captures['clean'] = clean
        stages.append({'name':'clean replay','status':'completed','seconds':time.monotonic()-capture_t,'reason':None})
    for label, folder in broken:
        if label == 'clean' or label in captures:raise ValueError('Each broken copy needs a unique name.')
        captures[label] = capture_data(folder)
    client = None
    if recording:
        from expectrail.recorded import MissingRecordedAnswer, RecordedClient, read_recording
        client = RecordedClient(read_recording(Path(recording)))
    for name in ('observer tuning','observer proof'):
        stages.append({'name':name,'status':'skipped','seconds':0,
                       'reason':'Recorded answers are displayed when available; no new calibration/proof run is claimed.'})
    objects = []; details = []
    for role in roles:
        prompt = next((s['body']['objects'][role]['prompt'] for s in specs if role in s['objects']), None)
        binding = config['bindings'].get(role, {})
        samples = []; sprite = None
        if clean:
            available = {f['frame']:f['objects'][role][0]['box'] for f in clean['observations']['frames'] if f['objects'].get(role)}
            for frame in select_three(available):
                path = clean['folder'] / 'frames' / f'f{frame:08d}.png'
                if not path.is_file():continue
                raw = read(path,16*1024*1024); native = png_size(raw); small = thumbnail(path)
                if small is None:continue
                data,size = small; image = asset(state,data,size,frame)
                image['engineBox'] = [v * size[i%2]/native[i%2] for i,v in enumerate(available[frame])]
                image['observerBox'] = None; image['score'] = None
                if client and prompt:
                    try:
                        detected = client.segment(path,prompt)
                        best = max((d for d in detected if d),key=lambda d:d['score'],default=None)
                        if best:
                            image['observerBox'] = [v * size[i%2]/native[i%2] for i,v in enumerate(best['box'])]
                            image['score'] = best['score']
                    except (ValueError, MissingRecordedAnswer):pass
                samples.append(image)
            pictured = [f for f in select_three(available) if (clean['folder']/'frames'/f'f{f:08d}.png').is_file()]
            if pictured:
                frame = pictured[0]; path = clean['folder']/'frames'/f'f{frame:08d}.png'
                box = available[frame]; native = png_size(read(path,16*1024*1024))
                crop = [max(0,box[0]),max(0,box[1]),min(native[0],box[2]),min(native[1],box[3])]
                if crop[2]>crop[0] and crop[3]>crop[1]:
                    small=thumbnail(path,crop=crop,side=96)
                    if small:sprite=asset(state,*small,frame)
        # Project art is the sprite. A replay crop may contain an overlay/occluder,
        # so it is only a fallback when the bound asset cannot be previewed.
        if binding.get('texture'):
            path=local(root,binding['texture'].removeprefix('res://'));small=thumbnail(path,side=96)
            if small:sprite=asset(state,*small,0)
            else:sprite=native_sprite(state,path) or sprite
        can_review = len(samples)==3 and sprite is not None
        objects.append({'role':role,'reviewable':can_review})
        details.append({'role':role,'prompt':prompt,'selector':binding.get('node',binding.get('group','Engine reference')),
                        'sprite':sprite,'samples':samples,'reviewable':can_review})
    checks = []
    for item in specs:
        row={'id':item['id'],'approved':item['approved'],**check_words(item['body']),'results':[]}
        for label,cap in captures.items():
            verdict=evaluate(item['body'],cap['observations'],route=cap['replay'].get('route',{}).get('name'),
                             trace=cap['trace'],capture_fps=cap['fps'])
            first=verdict.get('firstFrame');image=None
            if first is not None:
                path=cap['folder']/'frames'/f'f{first:08d}.png'
                if path.is_file():
                    small=thumbnail(path)
                    if small:image=asset(state,*small,first)
            row['results'].append({'copy':label,'result':verdict['result'],'reason':verdict['reason'],
                                   'firstFrame':first,'image':image,'source':'engine diagnostic; not vision evidence'})
        checks.append(row)
    for item in inputs.items():
        if sha(read(local(root,item[0])))!=item[1]:raise ValueError('Project inputs changed while the review was prepared.')
    timing={'format':'expectrail.onboard-timing/v1','startedAt':started,'readyAt':now(),
            'machineSeconds':time.monotonic()-t0,'humanSeconds':None,'approvedAt':None,'person':None,
            'state':'review-ready','stages':stages}
    record={'format':'expectrail.onboard-review/v1','project':str(root),'configPath':project_config.FILENAME,
            'configFileSha256':config_hash,'config':config,'route':{'path':route_name,'sha256':sha(route_raw),
            'document':route_doc,'existed':existed},'inputs':[{'path':p,'sha256':s} for p,s in inputs.items()],
            'objects':objects,'specs':[{k:v for k,v in s.items() if k!='body'} for s in specs],'timing':timing}
    validate_v1(record,'onboard-review')
    return record, {'project':root.name,'objects':details,'checks':checks,'timing':timing,
                    'observer':'Recorded answers' if client else 'No observer answers supplied; engine boxes only'}


def approve_answers(path):
    answers=load_strict(Path(path),'onboard-answers')
    person=answers['person'].strip()
    if not person or '\n' in person or '\r' in person:raise ValueError("A person's name is required; nothing was approved.")
    manifest=Path(answers['reviewFile']).absolute()
    if manifest.is_symlink():raise ValueError('The review record is a symbolic link.')
    timing_path=local(manifest.parent.resolve(), 'timing.json', exists=False)
    raw=read(manifest)
    if sha(raw)!=answers['reviewSha256']:raise ValueError('The saved review changed; create a new review page.')
    record=strict_loads(raw.decode());validate_v1(record,'onboard-review')
    root=Path(record['project'])
    if root.is_symlink() or not root.is_dir():raise ValueError('The reviewed project is missing or is a symbolic link.')
    root=root.resolve()
    if set(answers['objects'])!={r['role'] for r in record['objects']} or set(answers['checks'])!={s['id'] for s in record['specs'] if not s['approved']}:
        raise ValueError('The answers do not match the objects and draft checks on this page.')
    for item in record['inputs']:
        if sha(read(local(root,item['path'])))!=item['sha256']:raise ValueError(f"Reviewed input changed: {item['path']}. Create a new review page.")
    bodies={}
    for spec in record['specs']:
        body=strict_loads(read(local(root,spec['path'])).decode());validate(body,'test-spec')
        if approval.spec_sha256(body)!=spec['specSha256'] or sha(read(local(root,spec['path'])))!=spec['fileSha256']:
            raise ValueError(f"Check {spec['id']} changed since review; no approvals were written.")
        problems=approval.lint({k:v for k,v in body.items() if k!='approval'})
        if problems:raise ValueError('; '.join(problems))
        bodies[spec['id']]=body
    selected=[s for s in record['specs'] if not s['approved'] and answers['checks'][s['id']]]
    all_objects=all(answers['objects'].values()) and all(o['reviewable'] for o in record['objects'])
    if selected and not all_objects:raise ValueError('Confirm the measured objects before approving checks; no approvals were written.')
    stamp=now();opened=datetime.fromisoformat(answers['openedAt'].replace('Z','+00:00'))
    answered=datetime.fromisoformat(answers['answeredAt'].replace('Z','+00:00'));at=datetime.fromisoformat(stamp.replace('Z','+00:00'))
    if opened.tzinfo is None or answered.tzinfo is None or opened>answered or answered>at:
        raise ValueError('The review timing is invalid; no approvals were written.')
    config=deepcopy(record['config']);config.pop('draft', None)
    config['approvedContracts']=[s['path'] for s in record['specs'] if s['approved'] or s in selected]
    if all_objects:project_config.validate(config,root)
    route_record=record['route'];dest=local(root,route_record['path'],exists=route_record['existed'])
    if route_record['existed'] and sha(read(dest))!=route_record['sha256']:raise ValueError('The reviewed route changed.')
    config_path=local(root,record['configPath'],exists=record['configFileSha256'] is not None)
    if record['configFileSha256'] is None and config_path.exists():raise ValueError('A config appeared after review; it was preserved.')
    for spec in selected:approval.approve(local(root,spec['path']),person,at=stamp,expected_sha256=spec['specSha256'])
    if all_objects:
        if not route_record['existed']:
            dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(encoded(route_record['document']))
        config_path.write_bytes(encoded(config))
    timing=deepcopy(record['timing']);timing.update(person=person,approvedAt=stamp if all_objects else None,
        humanSeconds=(at-opened).total_seconds(),state='approved' if all_objects else 'declined')
    validate_v1(timing,'onboard-timing')
    timing_path.write_bytes(encoded(timing))
    return {'approved':[s['id'] for s in selected],'person':person,'timing':timing}
