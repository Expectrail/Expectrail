"""Advisory reproduction records and the optional repository JIT process boundary."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from expectrail import resources
from expectrail.gate import record
from expectrail.orchestrator.request import RequestError

NAME = 'playtest-reproduction.json'
FORMAT = 'expectrail.playtest-reproduction/v1'


def schema():
    return json.loads((resources.ROOT/'contracts/playtest-reproduction.v1.schema.json').read_text())


def check(doc):
    record.validate(doc, schema())
    if (doc['kind'] == 'none') != (not doc['checks']):
        raise RequestError('reproduction kind and check ids disagree')
    if doc['kind'] == 'generated-advisory' and doc['jitRunSha256'] is None:
        raise RequestError('generated reproduction needs a JIT record digest')


def build(kind, checks, reason, *, base_tree=None, clean_tree=None, jit_sha=None):
    doc = dict(format=FORMAT, kind=kind, advisory=True, checks=sorted(set(checks)), reason=reason[:512],
               baseTree=base_tree, cleanTree=clean_tree, jitRunSha256=jit_sha)
    check(doc)
    return doc


def write(folder, doc):
    check(doc)
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder)/NAME).write_text(json.dumps(doc, indent=2)+'\n')
    return doc


def read(folder):
    doc = record.read_json(Path(folder)/NAME, cap=65536, label='playtest reproduction')
    check(doc)
    return doc


def propose(doc, paths):
    """JIT stays repository-only, as before. Live transport needs an explicit role cap.

    The subprocess uses the existing JIT generator and keep rule. A snapshotted
    stand-in response never falls back to live transport. Without one, the existing
    spec-role cap must be explicitly configured before any live transport is bound.
    Missing JIT in a standard-library installation is explicit, never an accept.
    """
    command = [sys.executable, '-m', 'expectrail.jit.ingest', str(paths.request), str(paths.staging)]
    with (paths.root/'proposal-worker.log').open('wb') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                timeout=doc['limits']['timeoutSeconds'])
    if result.returncode:
        return write(paths.staging, build('none', [], 'generated-checks-unavailable: see proposal-worker.log'))
    result = read(paths.staging)
    if result['jitRunSha256'] is not None:
        data = record.read_json(paths.staging/'jit-run.json', label='JIT run')
        sha = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        if sha != result['jitRunSha256']:
            raise RequestError('generated reproduction JIT digest mismatch')
    return result
