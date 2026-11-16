"""Internally consistent, public capture mutations; standard library only."""
import hashlib
import json
import struct
import zipfile
import zlib


def png(width, height):
    """A valid RGB PNG, so dimension tests do not depend on PIL or a broken image."""
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data
                + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + b'\xff' * width * 3) * height))
            + chunk(b'IEND', b''))


def edit_capture(source, target, kind):
    """Change one head run and update all manifest/replay digests, leaving tree/policy fixed.

    These emulate a candidate producing structurally bad evidence, rather than a
    transport corruption already caught by the archive digest. Return changed PNGs.
    """
    with zipfile.ZipFile(source) as z:
        members = {name: z.read(name) for name in z.namelist()}
    name = next(name for name in members if name.startswith('head-1/') and name.endswith('/replay.json'))
    folder = name.rsplit('/', 1)[0]
    replay = json.loads(members[name])
    count = replay['capture']['frames']
    changed = {}
    if kind == 'extra':
        data = members[f'{folder}/frames/f{count-1:08d}.png']
        members[f'{folder}/frames/f{count:08d}.png'] = data
        replay['capture']['frames'] += 1
        replay['frameSha256'].append(hashlib.sha256(data).hexdigest())
    elif kind == 'resolution':
        index = min(10, count-1)
        path = f'{folder}/frames/f{index:08d}.png'
        width, height = struct.unpack('>II', members[path][16:24])
        data = png(width+1, height)
        members[path] = data
        replay['frameSha256'][index] = hashlib.sha256(data).hexdigest()
        changed[index] = data
    else:
        raise ValueError('unknown capture edit')
    members[name] = json.dumps(replay).encode()
    manifest = json.loads(members['manifest.json'])
    for run in manifest['runs']:
        if folder == run['group'] + '/' + run['route']:
            run['replay'] = hashlib.sha256(members[name]).hexdigest()
    members['manifest.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_STORED) as z:
        for path, data in members.items():
            z.writestr(path, data)
    return changed
