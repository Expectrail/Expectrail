"""Operator-only held-out binding. Requests contain a digest, never a private path.

Only explicitly configured runtime context is read. Tests author synthetic suites;
no private set is needed. A fresh snapshot feeds the existing gate, counts only.
"""
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from expectrail import contracts
from expectrail.gate import record
from expectrail.orchestrator.request import RequestError

ROOT_ENV = 'EXPECTRAIL_HELDOUT_DIR'
VISION_ENV = 'EXPECTRAIL_HELDOUT_VISION'
REFUSED = 'the operator held-out context is missing, changed or unsafe; nothing was judged'


def _read(request):
    try:
        value = os.environ.get(ROOT_ENV)
        if not value: raise ValueError()
        root = Path(value)
        if not root.is_absolute() or root.is_symlink() or root.resolve() != root: raise ValueError()
        for side in ('head', 'base'):
            ref = request[side]
            if ref:
                checkout = Path(ref['checkout']).resolve()
                if root == checkout or root.is_relative_to(checkout) or checkout.is_relative_to(root):
                    raise ValueError()
        # Read only the manifest and its named, bounded regular route files.
        data = {'manifest.json': record.read_bytes_capped(root / 'manifest.json', 1024*1024, 'held-out manifest')}
        entries = record.strict_loads(data['manifest.json'].decode())['routes']
        if not isinstance(entries, list) or not 1 <= len(entries) <= 64: raise ValueError()
        from expectrail.gate.verify import safe_relative
        for entry in entries:
            name = safe_relative(entry['file'], 'held-out route')
            path = root / name
            if name in data or path.resolve() != path: raise ValueError()
            raw = record.read_bytes_capped(path, 1024*1024, 'held-out route')
            contracts.validate(record.strict_loads(raw.decode()), 'route')
            data[name] = raw
        digest = hashlib.sha256()
        for name, raw in sorted(data.items()):
            digest.update(name.encode() + b'\0' + hashlib.sha256(raw).digest())
        return data, digest.hexdigest()
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        raise RequestError(REFUSED) from None


def bind(request):
    """CLI/operator producer. There is no project-config/report path selector."""
    result = copy.deepcopy(request)
    _, digest = _read(result)
    result['heldOut'] = {'suiteSha256': digest, 'framesToVisual': os.environ.get(VISION_ENV) == '1'}
    from expectrail.orchestrator.request import check
    check(result)
    return result


def validate(request):
    if 'heldOut' not in request: return
    _, digest = _read(request)
    binding = request['heldOut']
    if digest != binding['suiteSha256'] or (binding['framesToVisual'] and os.environ.get(VISION_ENV) != '1'):
        raise RequestError(REFUSED)


@contextlib.contextmanager
def snapshot(request):
    if 'heldOut' not in request:
        yield None
        return
    validate(request)
    data, digest = _read(request)
    if digest != request['heldOut']['suiteSha256']: raise RequestError(REFUSED)
    with tempfile.TemporaryDirectory(prefix='expectrail-private-context-') as tmp:
        root = Path(tmp)
        for name, raw in data.items():
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        yield root
        # A trusted context changing during a verification cannot silently pass.
        validate(request)
