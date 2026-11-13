# Local app: evidence, past runs and recorded observers (#370)

## What changed
Finished jobs open the existing evidence viewer and its offline export. Only jobs from this
app session expose files. Token, Host, traversal and symlink checks apply; the viewer script
is allowed by its hash. Past runs show stored jobs newest first with folders, time and result.
Observer wording reads the job's status or findings. Engine-only results are diagnostic.
Missing vision settings get plain instructions; an unavailable visual observer is not called a judge.

## What was run
- The required pinned fetch completed; Python 3.12.14.
- `python3 -m unittest tests.test_app` before implementation: 23 tests, 1 failure and 3 errors.
- `python3 -m unittest tests.test_app tests.test_viewer`: 48 tests, OK. Offline stand-ins only.
- `python3 -m unittest discover -s tests -t .` before: 2911 tests, 7 failures, 8 errors, 25 skipped.
- The same full suite after: 2917 tests, 7 failures, 8 errors, 25 skipped.
  Failure/error names and multiplicities match exactly; no new failures. Both logs are in the handover.
- `node --check` on the page's extracted script: OK (syntax only).

## Not done
Not looked at in a browser. No app trial on real games or paid model calls. CI not run here.
No installer or changes to the verifier's default observer rule. The architect must validate
on Linux, commit and push; no commit or pull request was made here. Store code is unchanged.

## Files
- `expectrail/app.py`
- `expectrail/app_page.py`
- `tests/test_app.py`
- `docs/app.md`
- `docs/new-work/2026-11-13-local-app-slice-2.md`

## Architect run (Linux)
On main 4675f9d: before 3014 tests OK (27 skipped); after 3020 tests OK (27 skipped). `tests.test_app tests.test_viewer` 48 OK. Not looked at in a browser.
