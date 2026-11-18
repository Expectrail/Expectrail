# Build the remaining offline repair paths (#433)

## What changed

Applied the under-review P0 audit patch first, then built its #433 agent follow-ups:
explicit bounded llm-patch selection for verify/app auto-fix, operator-pinned
held-out context on every fresh candidate, literal-command real-engine tests in
the existing sandbox CI collection, honest provider-only Run it provenance,
and a data-only draft publisher. Schemas, examples, producers and readers change
together. No second fixer, retry rule, sandbox or acceptance rule was added.

The publisher defaults to a no-write plan and uses only authenticated artifacts,
regular Git blobs and an isolated temporary index. Explicit publication creates
a new review branch and draft only, rechecking current authorization before every
write. Serialized plans cannot authorize publication. Stand-in APIs exercise it;
no real draft or branch was created.

The [current gap table and Sean actions](../repair-remaining.md) supersede the
historical audit's #433 inventory. Complete workflow proposals live under docs/;
Sean installs them. A plan-only operator wrapper reuses the existing kit's
model/tariff, ledger and cap policy for one literal live command case.

## What was run

- Before product edits, after applying the prerequisite audit: `python3 -m unittest
  discover -s tests -t .`, with no EXPECTRAIL variables: **4,534 tests, 522.400s,
  OK, 58 skips**. Raw log and wall-time result are in the handover.
- Red against the audit-only tree: **17 tests, 2 failures and 13 errors**. New
  modules/options are absent there; the operator module is one loader error.
  Product files were restored byte-for-byte afterward. This is recorded in
  `red-prerequisite-final.log` and `red-prerequisite-proof.json`; no existing
  assertion was weakened. Five controlled in-memory mutants each fail their
  targeted test: dropping the child's private binding, bypassing provider proof,
  removing the publisher's per-write current-head check, and omitting the writer's
  provider-only marker, and substituting the writer's copied-counter digest. Each is an assertion
  failure, not an import error; the source files were never changed for these
  mutants. [Compact proof](../measurements/433-remaining.json).
- Focused compatibility run: **128 tests, 43.430s, OK, 1 skip**, including packaging,
  existing repair/ingest/auto-fix/CI/schema tests and live-CLI bound refusals.
  Additional final focused checks, including the existing bounded-provider tests:
  **47 tests, 19.478s, OK**. The final full suite
  below includes the later repository-name and stopped-counter tests.
- Real Godot 4.7.2, real subprocess CLI, public fall-through patch, fixture fixer
  and trace-backed fixture observer: **3 tests, 823.827s, OK**. Direct repair and
  auto-fix each preserve the rejected original and get a distinct fresh gate
  accept with repair demonstrated. A bad fixture records two rejects and
  needs-review on exhaustion. Zero model calls, original game bytes unchanged.
  This host cannot map Bubblewrap UIDs; these runs explicitly used the local
  nonisolated diagnostic opt-in and Xvfb. **Not independent vision**. The existing
  `seeded-bugs` CI job collects the tests with `EXPECTRAIL_SANDBOX_TESTS=required`
  and therefore requires real sandboxed replays. That hosted run is not claimed.
- JavaScript syntax checked with `node --check`; both YAML proposals parsed and
  every embedded run script passed `bash -n`.

- Final full suite, again with no EXPECTRAIL variables: `python3 -m unittest
  discover -s tests -t .`: **4,559 tests, 411.871s, OK, 61 skips** (exit 0).
  No failing test. Wall time 412.641s. Raw before/after logs and failure names for
  the intermediate runs are in the handover.
- Dependency-blocking run denied numpy/PIL imports and made their discovery
  return absent: **50 tests, 20.659s, OK, 3 named engine skips**. It loaded the new
  engine helper/class and exercised the modified bounded-provider test module.
- `python -m agents.export_scan bench docs README.md apps --paths error`:
  **773 files, 0 errors, 0 warnings, exit 0**. The forbidden spent
  `bench/jit/blind-3` directory entry was temporarily moved outside the scan
  roots and restored in a finally block; none of its contents was read.

Full logs belong to the handover, not main. The complete changed docs blobs,
including the prerequisite audit, guides and small summary, are below 256 KiB.
No raw PNG/trace bulk is added to main.

The first full after-suite ran **4,559 tests in 428.444s**, with **1 failure and
61 skips**: `tests.test_llm_patch_bound.LlmPatchBound.
test_provider_violation_in_existing_repair_loop_never_verifies_or_retries`
expected the old two-field provenance object. The test now asserts the exact new
provider-only object and the copied counter digest, on both completed and stopped
paths. Its prior budget-stop/no-child/no-retry assertions remain. The final full
rerun is recorded below.

Intermediate failures retained in the handover: the first integration drafts had
fixture setup errors; the first real observer used an invalid name and was
correctly refused by the gate; an intermediate focused command named a nonexistent
`tests.test_ci_checks`, and the packaging guard refused a module filename containing
`heldout`. The module/example were renamed without changing the guard. None of
those failed runs is represented as a passing feature demonstration.

## Not done

No live model/fixer call, secret/account setup, workflow installation, hosted CI
run, GitHub mutation, push, merge, check approval or fourth-sample publication.
No actual held-out material was read. Muse/BYO live CLIs still stop with
`fixer-bound-unavailable`; their bounds were not loosened. Protected verifier,
anchored implementation, game sources, specs and .github files were not edited.

Sean still has to install/review the proposals and their permissions, push and
inspect required sandbox CI, authorize and record the literal live case(s), and
publish/check a genuine accepted fourth sample. Each action is spelled out in
[repair-remaining.md](../repair-remaining.md). **Part of #433**, not closure.

## Files

- `contracts/verify-request.v1.schema.json`, `contracts/repair-run.v1.schema.json`,
  new `repair-publication.v1.schema.json` and four matching examples.
- `expectrail/auto_fix.py`, app/page, orchestrator CLI/request/engines and new
  `orchestrator/private_context.py`: bounded selection and trusted context.
- `expectrail/repair.py`, new `repair_provenance.py`, Run it/viewer, `setup.py`:
  provider-only provenance and bound invocation counters.
- `tools/repair_draft.py`, `repair_live_case.py`, existing CI download/artifact
  helpers: trusted data publication and the deliberate operator wrapper.
- `tests/test_433_remaining.py`, `test_repair_draft.py`, `test_repair_live_case.py`,
  `repair_cli_fixture.py`; existing `test_replay_sandbox.py` adds three tests and
  `test_llm_patch_bound.py` strengthens provenance/digest assertions.
- This work log, `docs/repair-remaining.md`, the two proposed workflow text files,
  `docs/measurements/433-remaining.json`, app and Run it guides.
- The handover's combined patch also includes the prerequisite P0 audit patch;
  its historical work log is unchanged. An incremental patch is provided for
  an architect applying this only after that audit has landed.
