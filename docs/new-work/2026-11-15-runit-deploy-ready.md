# Prepare the Run it visitor service for Sean to deploy (#265)

## What changed

Added a numbered browser-first deployment guide with scoped tokens, dashboard-only
runtime secret entry, DNS/TLS, closed/open smoke checks and stop/recovery steps.
Added a credential-free smoke CLI with bounded HTTP, no redirects or dispatch retries,
a harmless bad-origin probe, and zero valid starts while health says closed.

The edge now atomically reserves quota, the active request and its record before
calling GitHub. An uncertain dispatch stays reserved and is reconciled by polling;
explicit refusal refunds quota and backs off for a minute. Provider fetches have
deadlines, request bodies are bounded while streaming, and error messages no longer
promise that an uncertain request started nothing. No secret values are logged.
Updated the contract descriptions, an example and the page's refusal wording.

## What was run

Required fetch of c169a5e0da304773587304ed47bc8aabcec80da7 and current main.
Base 2e7caa06f1b9f1962dbd4c7f67fdbe32d86e594c; branch chatgpt/265-deploy-ready.

- Full unittest discovery before and after through the handover's keyless runner.
  Before: 3568 tests, 0 failures, 0 errors, 46 skips, 330.472 seconds. After: 3581 tests, 0 failures, 0 errors, 46 skips, 358.418 seconds. Failure/error-name lists are both empty; raw logs and comparison are included.
- Final focused suite: 44 Python tests, OK, including the edge suite's 23 Node tests,
  schema validation of emitted API bodies, HTTP smoke tests against a loopback stub,
  and existing page/stub tests. No live service contacted.
- Node page tests execute the shipped script with a fake DOM, injected timers and
  fake fetch: lost/unreadable responses never claim nothing started; accepted means
  reserved and waiting. The first version of the new fixture omitted setTimeout,
  which caused its accepted-path assertion to fail. Added the missing timer stand-in;
  kept every assertion. Failed attempts and successful final logs are in the handover.
- A complete intermediate full run is retained; the final after log was started
  after the last code/test edit. No test removed, skipped or weakened.
- git diff --check; patch application to the named base and byte comparison;
  ZIP integrity and file checksums. No commits or pushes.

## Not done

No account, token, DNS, deployment, GitHub write, model call or spend. Dashboard
steps were checked against public documentation, not inside Sean's accounts.
Live closed/open smoke, deployed burst, first visitor, nightly platform check and
signed receipts remain. No workflow edited; the guide names the later nightly work.
The implementation uses an existing repository-scoped Actions token; GitHub cannot
restrict it to one workflow. Application quotas do not cap a paid host's HTTP bill.

## Files

- `.gitignore`
- `apps/run-it-edge/service.js`
- `apps/run-it-edge/worker.js`
- `apps/run-it-edge/wrangler.toml.example`
- `apps/run-it-edge/test/service.test.mjs`
- `contracts/run-it-api.v1.schema.json`
- `contracts/examples/run-it-api-unavailable.json`
- `docs/run-it-deploy.md`
- `docs/run-it.md`
- `docs/run-it/run-it.js`
- `tools/runit_smoke.py`
- `tests/test_runit_smoke.py`
- `docs/new-work/2026-11-15-runit-deploy-ready.md`

## Architect's change on integration

- The gap this change listed (the unrecorded recorded-fix sample was still in the service's
  allowlist, so a direct request could use up a slot and fail) is closed: `service.js` refuses it
  before admission with the existing `disabled` refusal, unless `RECORDED_FIX_OPEN` is "true"
  (`wrangler.toml.example`). Nothing is counted or dispatched. Test: "the unrecorded recorded-fix
  sample is refused before admission and counts nothing" (24 of 24 service tests pass).
