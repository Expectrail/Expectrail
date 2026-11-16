"""Untrusted playtest reports, translated to the ordinary configured-project job.

Only bug crosses into the existing bug-report path. Producer, route description and
fault metadata supply no check instruction, approval, provider setting or policy selection.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import stat
import unicodedata
from pathlib import Path
import subprocess

from expectrail import project_job, resources
from expectrail.gate import record
from expectrail.orchestrator import request

FORMAT = 'expectrail.playtest-report/v1'
SCHEMA_PATH = resources.ROOT / 'contracts/playtest-report.v1.schema.json'
MAX_BYTES = 1024 * 1024


def schema():
    return json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))


def check(doc):
    try:
        # Also reject non-finite floats supplied by a Python caller, not just the JSON reader.
        json.dumps(doc, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise request.RequestError('playtest report must contain finite JSON values') from exc
    problems = record.errors(doc, schema())
    if not problems:
        route_schema = json.loads((resources.ROOT / 'contracts/route.schema.json').read_text(encoding='utf-8'))
        problems = record.errors(doc['route'], route_schema, '/route')
    if problems:
        raise request.RequestError('playtest report: ' + problems[0])
    request.check_bug(doc)
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    if any(unicodedata.category(c) == 'Cc' and c not in '\t\r\n'
           for value in strings(doc) for c in value):
        raise request.RequestError('playtest report contains control characters; use plain text')
    fault, ticks = doc['fault'], doc['route']['ticks']
    try:
        finite = all(math.isfinite(fault['anchor'][key]) for key in ('x', 'y', 'tolerancePx'))
    except OverflowError:
        finite = False
    if not finite:
        raise request.RequestError('playtest anchor coordinates and tolerance must be finite engine numbers')
    if not 0 <= fault['preFaultTick'] < fault['faultTick'] < ticks:
        raise request.RequestError('playtest report needs 0 <= preFaultTick < faultTick < route.ticks')
    if any(e['tick'] >= ticks for e in doc['route']['events']):
        raise request.RequestError('playtest route event tick must be below route.ticks')
    if len((json.dumps(doc, indent=2) + '\n').encode('utf-8')) > MAX_BYTES:
        raise request.RequestError('playtest report exceeds 1048576 bytes')


def load(path):
    # Nonblocking open also refuses FIFOs without waiting for a writer. Never fetch a URL.
    try:
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        with os.fdopen(os.open(path, flags), 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise request.RequestError('playtest report must be a regular file')
            if info.st_size > MAX_BYTES:
                raise request.RequestError('playtest report exceeds 1048576 bytes')
            data = handle.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise request.RequestError('playtest report exceeds 1048576 bytes')
        doc = record.strict_loads(data.decode('utf-8'))
    except (OSError, UnicodeError, record.RecordError) as exc:
        raise request.RequestError('cannot read playtest report: ' + str(exc)) from exc
    check(doc)
    return doc


def write(path, doc):
    """Producer API: write only a valid report, never an approval or a selected check."""
    check(doc)
    Path(path).write_text(json.dumps(doc, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def obligation(doc):
    check(doc)
    return {'reached': [{'type': 'position-at-tick', 'tick': doc['fault']['preFaultTick'],
                         **copy.deepcopy(doc['fault']['anchor'])}]}


def prepare(store, report, project, *, timeout_seconds=request.DEFAULT_TIMEOUT_SECONDS,
            execution_class='diagnostic'):
    """Snapshot the unchanged project with its own policy and the report's start-to-fault route."""
    check(report)
    project = Path(project).expanduser().resolve()
    config = project_job.read_config(project)
    if config['adapter'] != 'godot':
        raise request.RequestError('playtest ingest supports only the shared Godot verifier')
    # The claimed commit must be the actual project checkout, not merely a label on a replay.
    try:
        commit = subprocess.run(['git', '-C', str(project), 'rev-parse', 'HEAD'], check=True,
                                capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise request.RequestError('playtest project must be in a git checkout with a HEAD commit') from exc
    if commit != report['target']['commit']:
        raise request.RequestError('playtest target.commit differs from the project HEAD')
    doc = project_job.prepare(store, project, project, intent='fix', bug=report['bug'],
                              head_commit=commit, base_commit=commit, timeout_seconds=timeout_seconds,
                              execution_class=execution_class)
    # Keep all configured checks and routes. A report only adds a route; it cannot select away
    # a configured check or route. Give it a trusted name, independent of every report string.
    name = 'playtest-' + hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()[:16]
    for side in ('head', 'base'):
        folder = Path(doc[side]['checkout']) / 'routes'
        route = copy.deepcopy(report['route'])
        route['name'] = name
        (folder / (name + '.json')).write_text(json.dumps(route) + '\n', encoding='utf-8')
    doc['coverage'] = obligation(report)
    doc['coverage']['routes'] = [name]
    # A folder job keeps no commit of its own (#539), so the checked target travels with the obligation.
    doc['coverage']['targetCommit'] = commit
    request.check(doc)
    return doc


def precheck(doc, checks, paths, replay, *, rule, visual, advance):
    """The authorized 3-of-3 front check, using the gate's judge and shared assessor.

    No alternative evaluator, repair decision or fixer. A stable public failure
    proceeds to the normal gate. Gaps and unstable failures stop before repair.
    """
    from expectrail import coverage
    from expectrail.gate import verify as gate
    from expectrail.coverage import all_of
    from expectrail.orchestrator.engines import Result

    if 'coverage' not in doc:
        return None
    base = Path(doc['base']['checkout'])
    game = base / doc['project']['game']
    named = json.loads(paths.status.read_text())['inputs']
    if named['baseTree'] != named['headTree']:
        raise request.RequestError('playtest intake requires the unchanged base and head game')
    selected = [r for r in checks.routes if r[0] in doc['coverage']['routes']]
    if len(selected) != len(doc['coverage']['routes']):
        raise request.RequestError('playtest coverage route is missing or invalid')
    config = gate.project_config(game)
    rate = int(config['captureFps']) if config is not None else 60
    summary = []
    paths.staging.mkdir(parents=True, exist_ok=True)

    def stop(reason):
        (paths.staging/'playtest-precheck.log').write_text(json.dumps(summary, indent=2)+'\n')
        return Result('needs-review', [reason], policy=checks.digest)

    outcomes = {}
    for n in range(1, record.REPAIR_RUNS + 1):
        for name, data, sha in selected:
            folder = paths.work/'playtest-precheck'/str(n)
            folder.mkdir(parents=True, exist_ok=True)
            route = folder/(name+'.json')
            route.write_bytes(data)
            advance('observing')
            if replay is None:
                run = gate.harness_replay(route, game, folder/name, True,
                    sandbox='require' if doc['executionClass'] == 'isolated' else None,
                    checkouts=(base,), adapter=doc['project']['adapter'], project=config)
            else:
                run = replay(route, game, folder/name, True)
            if run.get('tree') is not None and run['tree'] != named['baseTree']:
                raise gate.GameChanged('the base replay tree differs from the job inputs')
            reached = [coverage.checkpoint(c, run.get('trace')) for c in doc['coverage']['reached']]
            summary.append({'run': n, 'route': name, 'coverage': {'reached': reached}})
            if not all(value is True for value in reached):
                return stop('anchor-desync')
            # judge_arm owns observation conversion, applicability, coverage, evaluator and
            # observer combination. It consumes this already replayed arm, never a new replay.
            judged = gate.judge_arm(game, [(name, route, sha)], checks.specs, folder/'judged',
                lambda *_args: run, label='base', rule=rule, visual=visual, capture_fps=rate,
                on_phase=advance)
            summary[-1]['checks'] = [{'spec': key[0], 'result': value['result']} for key, value in judged.items()]
            for key, value in judged.items():
                if value['result'] != 'not-applicable':
                    outcomes.setdefault(key, []).append(value['result'])
    (paths.staging/'playtest-precheck.log').write_text(json.dumps(summary, indent=2)+'\n')
    if checks.problems or not outcomes:
        return stop('playtest-reproduction-inconclusive: no complete approved check set')
    if any(all_of(runs, 'fail', record.REPAIR_RUNS) for runs in outcomes.values()):
        return None  # The normal verifier alone decides the unchanged failing game.
    if all(all_of(runs, 'pass', record.REPAIR_RUNS) for runs in outcomes.values()):
        return stop('not-reproduced')
    return stop('playtest-reproduction-inconclusive: missing evidence or unstable failure')
