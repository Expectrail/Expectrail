# Separate the Run it browser and API smoke commands (#265)

## What changed
Replaces #484 on current main. Kept main's Chromium smoke command and tests
unchanged, and moved the deployed HTTP smoke to `tools/runit_api_smoke.py` and
`tests/test_runit_api_smoke.py`. Updated the allowlist, deployment commands and
guide. Updated the inherited deployment log's file names as the merge guard
explicitly requested; its historical results are unchanged.

The architect's admission safeguards, including `RECORDED_FIX_OPEN=false`, are
preserved. No service logic changed since the reviewed PR head.

## What was run
The three command/docs regressions fail on the old PR head and pass here.
The focused smoke tests run 25 tests, OK (one Chromium availability skip).
`node --test apps/run-it-edge/test/service.test.mjs`: 24 passed before and after.
Full before/after suite results and failure-name comparison are recorded in the
replacement PR and handover logs. The baseline ran 3,607 tests, OK (46 skipped).

Final full suite: 3,710 tests in 373.334 seconds, OK
(41 skipped); zero failures and errors. Compared failing test names
with the retained baseline: no new failures.
An earlier merged run exhausted disk (2 failures, 64 errors); its complete log
is retained. The final run above was rerun after freeing space, with no code
changes for that environment failure.

## Not done
No deployment, accounts, credentials, live model, spend, hosted CI or visitor
trial. The local browser smoke's Chromium integration could not run because the
Playwright browser executable is unavailable; its existing test remains intact.
The architect must commit the prepared merge with both parents and push the new
branch. Sean must confirm model-spending workflows still require his approval.

## Files
Rework: `.gitignore`, `tools/runit_api_smoke.py`,
`tests/test_runit_api_smoke.py`, `tests/test_runit_smoke_names.py`,
`docs/run-it-deploy.md`, `docs/run-it.md`,
`docs/new-work/2026-11-15-runit-deploy-ready.md`, and this log.
The replacement also carries #484's reviewed service, worker, Wrangler, API
contract/example and page changes; the full patch list is in `FILES.txt`.
