"""Audit the completed public command measurement against product statuses and raw traces."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from expectrail.orchestrator.playtest import load
from .command import classify, groups, report_documents as reports
from .producer import write_json


def audit(root):
    builds = json.loads((root / 'build-manifest.json').read_text())
    rows, checks = [], Counter()
    report_hashes = []
    for build in builds:
        folder = root / 'builds' / build['id']
        plan = json.loads((folder / 'plan.json').read_text())
        found = []
        for seed in range(plan['start'], plan['start'] + plan['count']):
            source = folder / 'seeds' / str(seed)
            summary = json.loads((source / 'summary.json').read_text())
            route = json.loads((source / 'route.json').read_text())
            replay = json.loads((source / 'replay/replay.json').read_text())
            raw_trace = source / 'replay/trace.json'
            data = raw_trace.read_bytes() if raw_trace.exists() else gzip.decompress(raw_trace.with_suffix('.json.gz').read_bytes())
            assert hashlib.sha256(data).hexdigest() == replay['trace']['sha256'], source
            assert replay['game']['tree'] == plan['tree'], source
            assert replay['engine']['version'] == plan['godotVersion'], source
            expected = reports(route, json.loads(data), plan['commit'], viewport=plan['viewport'])
            actual_paths = sorted((source / 'reports').glob('*.json'))
            actual = [load(p) for p in actual_paths]
            assert sorted(actual, key=lambda d:d['id']) == sorted(expected, key=lambda d:d['id']), source
            assert sorted(summary['reports']) == sorted(d['id'] for d in actual), source
            for path, doc in zip(actual_paths, actual):
                report_hashes.append({'path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
                found.append(doc)
        outcomes = Counter()
        for doc in found:
            intake = folder / 'intakes' / doc['id']
            result = json.loads((intake / 'result.json').read_text())
            statuses = list((intake / 'store/jobs').glob('*/status.json'))
            assert len(statuses) == 1, intake
            status = json.loads(statuses[0].read_text())
            precheck_file = statuses[0].parent / 'output/playtest-precheck.log'
            precheck = json.loads(precheck_file.read_text()) if precheck_file.exists() else []
            derived = classify(status, precheck)
            for key in ('outcome', 'anchorReached3of3', 'checks', 'reason', 'decision', 'job'):
                assert result[key] == derived[key], (intake, key)
            assert result['exit'] in (0, 1, 2, 3, 4), intake
            outcomes[derived['outcome']] += 1
            checks.update(derived['checks'])
            assert status['budget']['totalReservedUsd'] == 0, intake
            assert not status['budget']['phases'], intake
            argv = json.loads((intake / 'argv.json').read_text())
            assert argv[1:4] == ['-m', 'expectrail.cli', 'ingest'], intake
            assert '--propose' not in argv and '--repair' not in argv, intake
        grouped = groups(found)
        saved = json.loads((folder / 'results.json').read_text())
        assert saved['reports'] == len(found) and saved['groups'] == grouped, folder
        assert saved['outcomes'] == dict(outcomes), folder
        rows.append({'build': build['id'], 'kind': build['kind'], 'seeds': plan['count'],
                     'raw': len(found), 'grouped': len(grouped), **{key: outcomes[key] for key in (
                         'anchor-desync', 'approved', 'not-reproduced', 'inconclusive', 'job-error', 'unclassified')}})
    manual = []
    for path in sorted((root / 'false-reports').glob('handwritten-*.json')):
        doc = load(path)
        intake = root / 'false-reports/intakes' / doc['id']
        result = json.loads((intake / 'result.json').read_text())
        status_path, = (intake / 'store/jobs').glob('*/status.json')
        status = json.loads(status_path.read_text())
        precheck = json.loads((status_path.parent / 'output/playtest-precheck.log').read_text())
        derived = classify(status, precheck)
        assert all(result[key] == derived[key] for key in ('outcome', 'anchorReached3of3', 'checks', 'reason'))
        manual.append({'id': doc['id'], **derived})
    assert len(manual) == 2, 'two hand-written false reports required'
    result = {'falseReports': manual, 'builds': rows, 'approvedChecks': dict(checks), 'reports': report_hashes,
              'rawReports': sum(r['raw'] for r in rows), 'groupedReports': sum(r['grouped'] for r in rows)}
    write_json(root / 'audit.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    result = audit(args.root.resolve())
    print(json.dumps({k:v for k,v in result.items() if k != 'reports'}, indent=2))


if __name__ == '__main__':
    main()
