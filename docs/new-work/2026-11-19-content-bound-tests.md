# Tests no longer borrow a committed check's approval, and the known bench names its rule (#644)

## What changed
Sean's #642 approves the four committed Godot checks again with content binding (`specSha256`, #420).
This branch carries his commit unchanged and fixes the tests that assumed those checks carry an
approval from before binding. No product code changes except one line in the known bench.

- `tests/approved_copies.py` (new): `reapproved(doc)` approves a copy through `expectrail.approval.approve`
  in a temporary folder it creates and deletes; `legacy(doc)` builds an approval from before content
  binding in memory. Nothing in it writes into the repository.
- `tests/test_ci_gate.make_repo`: a `spec_edit` copy is approved again inside the test's own checkout
  (an edit voids a bound approval), and `legacy=True` gives the check an approval from before binding.
  This fixes the 7 `test_exercised_coverage.CoverageGateTest` cases and `HeldOutScopeTest` (scoped).
- `VerifyTest`, "a spec's id used by two files", and `test_orchestrator`'s "a file" form: the copy with a
  new id is approved again in a temporary folder, so it still counts as a second approved check.
- `test_approval_binding`: the legacy example is built (`legacy_spec()`) instead of read from the
  committed check, in every test that is about an approval from before binding (the digest test, the
  blank-name case, the schema, the reader, the gate, the Spark comparison, the merge guard). New test:
  every committed check that carries an approval is `bound`.
- `test_spec_writer`: a committed check's approval has the keys `at`, `by`, `specSha256` and its state is
  `bound` (it was `at`, `by`).
- `test_two_observers.EngineOnlyTest`: the committed check now gives `["all 1 checks pass"]`, and a
  legacy copy still gives the note after it.
- `tests/fixtures/clipped-player/kinematic-findings-before.json`: re-recorded by running
  `tests.test_clipped_player.recorded_findings(AnchoredObserver)` (recorded vision answers, no model).
  The only differences, in all three entries: the legacy note is gone from `reasons`, and the spec's
  record digest is the re-approved file's (`4829b493…` to `cf617839…`). Every other byte is the same.
- `expectrail/gate/known_bench.py`: `run_case` passes `rule=engine-only` to the gate. The record states
  `"rule": "engine-only"` (a const in its schema), but the runner took the gate's default, which became
  both observers in #602. Re-run without this, every no-intent row turned needs-review ("no visual
  observer was asked") under a record that still said engine-only. The test's stand-in gate now takes
  `rule`, and a test checks the rule each call is given.
- `bench/jit/known/gate.json` and `gate.md`: re-recorded on the real engine, since the spec bytes changed.

## What was run
- Before the fixes, on this branch merged with main at 9218e13, the eight modules named in #644:
  367 tests, 15 failures and 5 errors (the list in #644, less the film rehearsal, which is in the full
  suite).
- `python3 -m expectrail.gate.known_bench run --jobs 2` (Godot 4.7.2-stable, this cloud container, no
  model). First run, before the rule fix: 13 min 24 s, every no-intent row needs-review, as above.
  Second run, with the rule named: see the pull request for its result.
- The full suite: in the pull request's description.

## Not done
- No committed approval was changed: the four committed checks are as Sean's commit left them.
- The legacy path is still read (an approval from before binding still counts and is named); only the
  tests' example of it moved into the tests.

## Files
- `tests/approved_copies.py`
- `tests/test_ci_gate.py`, `tests/test_approval_binding.py`, `tests/test_spec_writer.py`,
  `tests/test_two_observers.py`, `tests/test_orchestrator.py`, `tests/test_gate_known_bench.py`
- `tests/fixtures/clipped-player/kinematic-findings-before.json`
- `expectrail/gate/known_bench.py`
- `bench/jit/known/gate.json`, `bench/jit/known/gate.md`
- `docs/new-work/2026-11-19-content-bound-tests.md`
