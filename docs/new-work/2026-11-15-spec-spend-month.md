# Spec drafting cap and the model month (#267)

## What changed

Spec drafting requires `EXPECTRAIL_SPEC_USD_CAP` at every real sender and reserves
$0.05 before each request, including provider retries and schema fallbacks. Fixtures
remain usable without a cap and count when one is set. `spark_open.counting` preserves
the sender's accounting marker. Feedback's shared transport applies the spec cap only
to spec drafting.

`EXPECTRAIL_MODEL_MONTH_LEDGER` opts into a separate combined $200 UTC month ledger
for Glimmer, Muse, triage and spec drafting. It reserves each role's whole process cap
before its first request. Two processes share a stable file lock; writes use fsync
and atomic replacement. Invalid, unreadable and failed ledgers stop by name, including
invalid old months. The new schema, example, writer and reader ship together.

`job-budget.v1` includes the spec cap and drafting phase. Its schema formatting is
preserved. Shared role tables update its existing writer and reader without editing
`build_job_budget`; an exact source comparison confirmed that function is unchanged.

## What was run

Read AGENTS.md, merged PR #436 and its spend/Glimmer/contracts context before editing.
Base: `7ed6106a1ef49e990282979963d950b0f8bc86fb`, branch `chatgpt/267-spend-month`.
Fetched the pinned AGENTS.md prerequisite commit once.

`python3 -m unittest tests.test_spend tests.test_spec_spend_month tests.test_open_weights tests.test_feedback tests.test_spark_open tests.test_spec_writer tests.test_byo_wiring tests.test_byo_providers tests.test_schema_pattern`
passed: 135 tests. New regression coverage includes each direct and wrapped sender,
no-cap stops, exact single holds, fixture retries, provider retries/fallbacks, the spec
budget round-trip, all four month roles, invalid and disappeared ledgers, rollover,
atomic-write failure and two real Python processes competing for the month limit.

`python3 -m unittest discover -s tests -t .`: final corrected run passed **3,753 tests,
42 skipped**, in 345.521 seconds. The shell had zero `EXPECTRAIL_*` variables.
An earlier 3,738-test run also passed; adding the new tests exposed inherited SAM
usage in two new test fixtures, corrected by saving/resetting/restoring that counter.
The isolation check (`python3 -m unittest tests.test_sam tests.test_spec_spend_month`)
passed 89 tests. Full development logs are retained in the handover.

No live model calls were made. `git diff --check` and compile checks passed. The patch
also passed `git apply --check` on fetched main `ccb58ef2105c707666c80334044dbae448b56320`.

## Not done

Workflow caps and a persistent ledger location remain Sean's deployment steps. No
live schema, timeout or bill comparison was run. Holds are conservative reservations,
not bill totals. The vision ledger remains separate. No change to `build_job_budget`,
`expectrail/orchestrator/`, `expectrail/cli.py`, `expectrail/gate/verify.py` or `.github/`.

## Files

- `expectrail/spend.py`, `expectrail/spec_writer.py`, `expectrail/providers.py`
- `agents/feedback.py`, `agents/spark_open.py`
- `contracts/job-budget.v1.schema.json`, `contracts/examples/job-budget.json`
- `contracts/model-month.v1.schema.json`, `contracts/examples/model-month.json`
- `tests/test_spec_spend_month.py`, `tests/test_open_weights.py`, `tests/test_byo_wiring.py`, `tests/test_schema_pattern.py`
- `docs/spend-caps.md`, this work log
