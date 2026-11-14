# Spend caps for Glimmer, Muse and triage, and the vision month (#267)

## What changed
Vision already stops at `EXPECTRAIL_SAM_USD_CAP`. The other roles that send a request now do the
same, and the month's vision total is counted against Sean's $200 limit.

- Glimmer (`EXPECTRAIL_GLIMMER_USD_CAP`), Muse (`EXPECTRAIL_MUSE_USD_CAP`) and triage
  (`EXPECTRAIL_TRIAGE_USD_CAP`) each take a hold before the request is sent. A missing cap on a
  live call, a cap that is not an amount, or a hold that would pass the cap stops the request and
  says why. Nothing is sent. A stop is not an offline fallback: `BudgetStop` is not a
  `RuntimeError`, so triage does not turn it into the offline report.
- A stand-in sender (a test transport, a recorded answer) is not held to a cap that was never set,
  the same rule SAM already uses. A cap that is set applies to the stand-in too. Glimmer's real
  sender and `warm` refuse before they open a connection when no cap is set.
- The holds are not vendor bills. Glimmer and triage hold $0.05 a request. Muse holds $1.00 an
  invocation, before `muse exec` starts. Vision images stay at Meta's list price in
  `agents.sam_observations` ($2.50 per 1,000 images). Each provider's record says which role it
  can be asked for, the cap variable, the hold and why that figure was chosen.
- `expectrail.job-budget/v1` is the per-job budget: the cap for each role, what each phase held,
  and whether the run was stopped. Schema, example, writer and reader land together.
  `expectrail.provider-capability/v1` is one record per provider. `expectrail.vision-month/v1` is
  the month's running total.
- When `EXPECTRAIL_VISION_MONTH_LEDGER` points at a file outside this repository, the first SAM
  request of a process reserves that run's whole cap (its worst case) against the month, under a
  file lock, and refuses the run before a request is sent if the month plus the cap would pass
  $200. A second image in the same process does not reserve the cap again. A new calendar month
  starts again at zero. With the variable unset the month is not counted and SAM behaves as it did.

## What was run
- `python3 -m unittest tests.test_spend tests.test_glimmer tests.test_sam.SpendCapTest tests.test_gateway tests.test_byo_wiring tests.test_agents.MuseJudgeTest.test_nonzero_muse_exit_fail_closed_even_with_decision`: 89 tests, OK. The 15 new ones are in `tests.test_spend`.
- `python3 -m unittest tests.test_schema_pattern tests.test_spend`: 25 tests, OK, after the new contract patterns got samples.
- `python3 -m unittest discover -s tests -t .` on Python 3.10.22, before the change and after, on base `6e6ca6a8a85f7518cc890116bdcfd02d2c9d010c`.
  Before: `Ran 3174 tests in 300.494s`, `FAILED (failures=8, errors=8, skipped=54)`.
  After: `Ran 3189 tests in 281.634s`, `FAILED (failures=8, errors=8, skipped=54)`.
  The 15 extra tests are this change. The 16 failures and errors are the same names before and after.
  This machine's Godot cannot open a display (`libXcursor.so.1` is missing), and a failed engine
  raises `SystemExit`, which aborts unittest before it prints a count. For both runs the binary's
  path was a directory, so `real_godot` skips and `get_godot.sh` does not download a real binary
  in the middle of the suite. The 16 that fail here are `tests.test_package` and
  `tests.test_python_floor` (this Python is 3.10 and has no `tomllib`; the package requires
  3.12), seven `tests.test_doctor` checks, six `tests.test_runit_site` errors, and
  `tests.test_runit_edge.StubBurstTest`.
- **No live call was made.** Nothing here was sent to Glimmer, Muse, triage or SAM.

## Not done
- Spec drafting's cap is left for later. `expectrail/spec_writer.py` was not touched.
- No workflow sets any cap, or `EXPECTRAIL_VISION_MONTH_LEDGER`. A live call from a workflow still
  stops with the missing-cap reason. Putting the caps on the live workflows, and a permission that
  can write the month's file, needs Sean. No workflow file is in this change.
- The live schema, error and timeout checks from main are not here (`needs-sean`).
- The Glimmer, Muse and triage holds were not compared with a bill. They are a ceiling taken
  before the provider answers, not the invoice.
- The caps are still per process. The month's file is what holds vision across processes, and only
  when the ledger variable is set. Glimmer, Muse and triage have no month total yet.
- The suite on this machine is 3,189 tests, not a green 3,260: the engine tests skip, and the 16
  failures above are on the clean tree too.

## Files
`expectrail/spend.py`, `contracts/job-budget.v1.schema.json`, `contracts/vision-month.v1.schema.json`,
`contracts/provider-capability.v1.schema.json`, `contracts/examples/job-budget.json`,
`contracts/examples/vision-month.json`, `contracts/examples/provider-capabilities/` (one file per
provider), `agents/sam_observations.py`, `agents/glimmer_client.py`, `agents/sandbox.py`,
`agents/triage.py`, `setup.py`, `docs/sam.md`, `tests/test_spend.py`, `tests/test_schema_pattern.py`,
`tests/test_gateway.py`, `tests/test_agents.py`, `tests/test_byo_wiring.py`
