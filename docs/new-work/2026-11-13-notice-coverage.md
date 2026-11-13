# Report a ledger notice that no entry counts (#244)

## What changed
`recheck` gathers the count entries from every row citing the same run. Every notice selected by
their `titled` and `not` rules must be included in at least one entry's `of`. A notice whose values
match no entry is reported as "cannot tell", with its title and job. This uses the existing problem
report, not an exception. Overlapping entries are allowed. `has` decides `n`, not coverage; an entry
without `where` includes every notice its title rules select. Explicit title exclusions still apply.

The schema description, contract example, renderer and contract documentation explain the rule.
The example is also checked against the saved public notices. Existing single-entry tests now
assert the additional uncounted notices as well as their original count or malformed-data problem.
No test was removed or skipped.

## What was run
- `python3 --version`: Python 3.12.14.
- Before editing, `python3 -m unittest discover -s tests -t .` on unchanged main
  `2f7e35a74b3f3660da5509508e2bed7ea4bd2818`: 2553 tests, 7 failures, 8 errors, 25 skipped.
  The failure/error names are exactly the accepted baseline's 15 entries; none added or removed.
- After the change, `python3 -m unittest discover -s tests -t .`: 2562 tests, 7 failures,
  8 errors, 25 skipped. Compared the full failure/error names with the before log and the accepted
  baseline log: the same 15 entries, no others. Nine tests added; no skip added by this change.
- Test first: `python3 -m unittest tests.test_capability_counts.NoticeCoverageTest` before the fix:
  8 tests, 8 failing assertions (including subtests). I read the failures: uncounted notices returned
  no problem. The tests also cover no notices, complete coverage, overlap, no `where`, title rules,
  coverage across rows, and separation between runs.
- `python3 -m unittest tests.test_capability_counts tests.test_capability_runs tests.test_capabilities`:
  157 tests, OK.
- `python3 -m expectrail.capabilities render`: wrote `docs/capabilities.md`.
- `python3 -m expectrail.capabilities check`: exit 0, no problems.
- Live GitHub recheck of the two tied discovery runs: exit 0, `2 runs read, 0 problems`.
  Each returned `completed, success, attempt 1, 12 jobs, 22 notices`. The connector cannot read
  annotations and this machine's `gh` is not logged in, so the existing readers used the public
  GitHub API through `urllib.request`, without credentials. Exact command:

```sh
python3 - <<'PY'
import urllib.request
from expectrail import capabilities as cap, capability_runs as runs

doc = cap.load()
wanted = {'41248745687', '41319184209'}
for row in doc['rows']:
    row['evidence'] = [ev for ev in row['evidence']
                       if ev['kind'] == 'run' and runs._split(ev['ref'])[0] in wanted]
doc['rows'] = [row for row in doc['rows'] if row['evidence']]
doc['timings'] = []
def call(path):
    with urllib.request.urlopen('https://api.github.com/' + path, timeout=30) as response:
        return response.read().decode('utf-8')
problems, checked = runs.recheck(doc, runs.github_reader(call), runs.github_notices(call))
print('\n'.join(checked + problems))
print(f'{len(checked)} runs read, {len(problems)} problems')
raise SystemExit(1 if problems or len(checked) != len(wanted) else 0)
PY
```

## Not done
The other items on #244 are untouched: workflow changes, the untied counts, CI permissions,
a person's review of grades and statuses, and the wall-time measurement on main. CI is not run;
this change is not ready until every CI check is green. Live engine and model checks: not run.
Rechecking every cited run against GitHub: not run; the live check was limited to the two above.
GitHub rejected both the issue label and claim comment with HTTP 403. The claim text is in the
handover; it was not posted. No pull request was opened.

## Files
- `expectrail/capability_runs.py`
- `expectrail/capabilities.py`
- `tests/test_capability_counts.py`
- `contracts/capabilities.v1.schema.json`
- `contracts/examples/capabilities.json`
- `docs/contracts.md`
- `docs/capabilities.md`
- `docs/new-work/2026-11-13-notice-coverage.md`
