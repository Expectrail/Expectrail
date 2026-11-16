"""Opt-in handoff to #433. Reports cannot select a fixer or supply its evidence."""
from __future__ import annotations

import tempfile
from pathlib import Path

from expectrail import contracts
from expectrail.gate import record
from expectrail.orchestrator import reproduction, request, store


def run(jobs, job, *, attempts=3, fixture=None, spawn_worker=None, agent="muse-code"):
    status, original = jobs.status(job), jobs.request(job)
    if status['phase'] != 'completed' or 'coverage' not in original:
        raise ValueError('ingest repair needs a completed playtest intake')
    if type(attempts) is not int or not 1 <= attempts <= 10:
        raise ValueError('attempts must be between 1 and 10')
    paths = jobs.paths(job)
    evidence = reproduction.read(paths.output)
    kind = evidence['kind']
    # Re-read the bound evidence rather than trusting a CLI string or report prose.
    if evidence != status.get('reproduction') or evidence['baseTree'] not in (None, status['inputs']['baseTree']):
        raise ValueError('reproduction evidence differs from the saved job')
    if request.inputs(original) != status['inputs']:
        raise ValueError('the intake inputs changed; ingest again')
    why = evidence['reason']
    eligible = kind == 'approved' and status['decision'] == 'reject' and evidence['baseTree'] == status['inputs']['baseTree']
    if eligible:
        summary = record.read_json(paths.output / 'playtest-precheck.log', label='base precheck')
        checks = request.read_checks(original)
        approved = {s['id'] for s in checks.specs}
        # The gate's precheck already judged these runs. Validate its recorded 3/3 proof;
        # no replay, evaluator, keep rule or candidate decision is implemented here.
        eligible = bool(evidence['checks']) and set(evidence['checks']) <= approved
        for spec in evidence['checks']:
            eligible = eligible and any(
                [r['run'] for r in summary if r['route'] == route
                 and all(x is True for x in r['coverage']['reached'])
                 and any(c['spec'] == spec and c['result'] == 'fail' for c in r.get('checks', []))]
                == list(range(1, record.REPAIR_RUNS + 1))
                for route in original['coverage']['routes'])
        if not eligible:
            why = 'approved reproduction lacks the recorded three-of-three base proof'
    if kind == 'generated-advisory':
        why = 'a person must approve a check first; generated advisory checks cannot start repair'
    # Deliberately import/call the repair service only after the eligibility check.
    from expectrail import repair
    if eligible:
        path, doc = repair.repair(jobs, job, attempts=attempts, fixture=fixture, spawn_worker=spawn_worker, **({"agent": agent} if agent != "muse-code" else {}))
        attempted = bool(doc['attempts'])
    else:
        folder = Path(tempfile.mkdtemp(prefix='repair-', dir=paths.root))
        now = store.stamp()
        doc = {'format': 'expectrail.repair-run/v1',
               'parent': {'job': job, 'decision': status['decision'],
                          'headTree': status['inputs']['headTree'], 'failing': []},
               'fixer': {'source': 'not-run', 'sandboxed': False},
               'budget': {'attempts': attempts, 'usdCap': None}, 'attempts': [],
               'stop': {'reason': 'needs-review', 'detail': why[:600]},
               'result': {'decision': 'needs-review', 'job': None, 'patch': None},
               'machineWritten': True, 'review': contracts.schema_v1('repair-run')['properties']['review']['enum'][2],
               'startedAt': now, 'finishedAt': now}
        path, attempted = folder / 'repair-run.json', False
    # Ordered for consumers: reproduction, attempt, then the loop's candidate decision.
    doc = {'format': doc.pop('format'), 'reproduction': {'kind': kind, 'checks': evidence['checks']},
           'repairAttempted': attempted, **doc}
    return repair.write_run(path.parent, doc)
