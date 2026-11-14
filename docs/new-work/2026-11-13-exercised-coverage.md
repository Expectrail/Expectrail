# Exercised coverage and complete engine records (#256, #357)

## What changed

Added optional frame-count/share, route-scope and engine checkpoint obligations to test-spec/v0,
with draft spec, verdict and findings examples. Geometry and trace evaluators share the existing
not_exercised evidence policy. Required checks that were not exercised need review; nonapplicable
routes are explicit and are not counted as passing checks. The trusted findings reader recomputes
scope, required counts and missing required routes. Pages and comments name nonapplicable checks.
The engine-only gate now enforces engine_gap before a pass, including complete tick identities and
window frames. Assertion sampling remains advisory and cannot bypass final coverage requirements.

No approved spec file or approval was edited. No game, app, orchestrator, route command or workflow
was edited. Successful replay stand-ins now emit complete records; assertions were not loosened.
The only change in test_two_observers.py is the engine-only test named by #357.

## What was run

The required fetch of c169a5e0da304773587304ed47bc8aabcec80da7 completed before testing.
Base main: 1f2ff7c757d2a0152b6e5dd69b7b02fb06bb1553.

- Before: `python3 -m unittest discover -s tests -t .`: 3,064 tests, 3 failures, 3 errors,
  31 skipped. After: 3,090 tests, 3 failures, 3 errors, 31 skipped.
  Exact failure/error names and kinds are identical; no new failures/errors or skips.
  `VALIDATION.json` and both full logs are included in the handover.
- Targeted coverage, geometry/trace evaluator, two-observer, gate, adapter, viewer, SAM stand-in
  and package tests: 346 passed. Focused evaluator/coverage run: 46 passed.
- One initial after-run was interrupted to fix a new test's accidental shared-fixture mutation.
  It is retained separately and is not the final comparison. No existing assertion was loosened.
- A development run found four benchmark callers without a `passed` count. The existing
  call format is preserved; unchanged benchmark and coverage tests passed (44 tests).
  The final full run includes that fix.
- Real Godot 4.7.2 headless smoke replays, clean and seeded bug: each had 240 trace rows for
  240 route ticks and 120 observation frames reconstructed from the trace. Zero images were
  captured. Baseline and changed gate gave exactly the same results: clean pass, bug fail.
  The reproducible script and output are in the handover.

Unchanged full-suite failure/error names:

- ERROR: `setUpClass (tests.test_event_input.EventInputTest)`
- ERROR: `setUpClass (tests.test_pause_input.PauseInputTest)`
- ERROR: `test_a_real_fix_is_accepted_with_the_private_sessions_mounted (tests.test_web.FixLoopTest.test_a_real_fix_is_accepted_with_the_private_sessions_mounted)`
- FAIL: `test_its_own_tests_pass_and_every_body_it_sent_is_in_the_contract (tests.test_runit_edge.EdgeFunctionTest.test_its_own_tests_pass_and_every_body_it_sent_is_in_the_contract)`
- FAIL: `test_a_bug_its_checks_cannot_see_is_not_detected_without_sam (tests.test_web.FixLoopTest.test_a_bug_its_checks_cannot_see_is_not_detected_without_sam)`
- FAIL: `test_without_the_private_sessions_nothing_is_accepted (tests.test_web.FixLoopTest.test_without_the_private_sessions_nothing_is_accepted)`

## Not done

No rendered-frame run (xvfb-run is unavailable here), native macOS or Windows run, paid model call,
commit, push, approval or GitHub write. The full suite is not claimed green. The architect must
validate the patch on Linux before pushing and opening the PR.

## Files

- `agents/sam_observations.py`
- `contracts/examples/findings-coverage.json`
- `contracts/examples/test-spec-coverage.json`
- `contracts/examples/verdict-coverage.json`
- `contracts/findings.schema.json`
- `contracts/test-spec.schema.json`
- `contracts/verdict.schema.json`
- `docs/exercised-coverage.md`
- `docs/new-work/2026-11-13-exercised-coverage.md`
- `expectrail/coverage.py`
- `expectrail/evaluator.py`
- `expectrail/gate/comment.py`
- `expectrail/gate/page.py`
- `expectrail/gate/record.py`
- `expectrail/gate/verify.py`
- `expectrail/trace/evaluator.py`
- `expectrail/viewer.py`
- `setup.py`
- `tests/coverage_replays.py`
- `tests/test_ci_gate.py`
- `tests/test_engine_from_adapter.py`
- `tests/test_exercised_coverage.py`
- `tests/test_orchestrator.py`
- `tests/test_two_observers.py`

## Architect run (Linux, main c5d1e533, Godot 4.7.2)
Full suite: 3111 tests, OK, 27 skipped. Engine-gated modules with EXPECTRAIL_ENGINE_TESTS=required (body_box, event_input, ground_under, pause_input, second_project): 59 OK. check-real-replays.py: clean pass, bug fail, 240 rows, 120 frames. Unchanged decisions: the three Run it samples accept, reject, accept with their recorded vision answers; the orchestrator sample accept, reject, accept.

## Architect fix after the merge guard (held-out scope)
The guard found that a spec scoped with `coverage.routes` was judged on no held-out route and the gate accepted with zero held-out checks. Fixed: held-out routes judge the spec without its scope (`verify.unscoped`), and `record.decide` makes a judged held-out set with no checks needs-review. `tests.test_ci_gate.HeldOutScopeTest` holds both; it failed (accept) before the fix.
