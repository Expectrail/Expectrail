"""Check CI's no-settings sample/verify JSON against its saved, sandboxed engine evidence."""
import argparse
import json
from pathlib import Path

from expectrail.gate import record
from expectrail.orchestrator import sample as samples, store


def check(doc, jobs_root: Path, *, sample: bool) -> None:
    jobs = store.JobStore(jobs_root)
    if sample:
        assert [r['case'] for r in doc] == [c[0] for c in samples.CASES], doc
        statuses = [r['status'] for r in doc]
        expected = ['needs-review', 'reject', 'needs-review']
    else:
        statuses, expected = [doc], ['needs-review']
    assert [s['decision'] for s in statuses] == expected
    for status in statuses:
        store.check_status(status)
        assert status == jobs.status(status['id']), 'JSON differs from the saved job'
        assert status['phase'] == 'completed' and status['output'] == 'output', status
        diagnostics = status['diagnostics']
        assert len(diagnostics) == 2 and all(d['code'] == 'PROVIDER_FAILED' for d in diagnostics), diagnostics
        for setting in ('MODEL_API_KEY', 'EXPECTRAIL_SAM_USD_CAP'):
            assert any(setting in d['detail'] and d['fix'].startswith('set ' + setting) for d in diagnostics), diagnostics
        findings = record.read_record(jobs.paths(status['id']).output / 'findings.json')
        assert findings['decision'] == status['decision']
        assert findings['observers'] == status['observers'] == {'rule': 'both', 'visual': None}
        checks = findings['checks']
        assert checks and all(c['observed']['after']['engine'] in ('pass', 'fail') for c in checks), checks
        assert all(c['observed']['after']['visual'] == 'not-asked' for c in checks), checks
        assert (status['decision'] == 'reject') == any(c['observed']['after']['engine'] == 'fail' for c in checks)
        isolation = findings['isolation']
        assert isolation['replays'] > 0 and isolation['sandboxed'] == isolation['replays'], isolation
        print(status['id'], status['decision'], isolation['replays'], 'sandboxed replays; vision did not run')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('json', type=Path)
    parser.add_argument('jobs_root', type=Path)
    parser.add_argument('--sample', action='store_true')
    args = parser.parse_args()
    check(json.loads(args.json.read_text()), args.jobs_root, sample=args.sample)
