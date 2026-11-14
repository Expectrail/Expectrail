# A first route from the project's input map (#329)

## What changed

Added `expectrail route --project PATH --auto --out ROUTE`. It reads project-defined Godot
input actions, uses built-in UI actions only for an empty map, and writes the existing route/v0
format with seed 1, movement holds, repeated short presses and pauses. Three complete headless
harness traces must agree before publication. Differences name their ticks and metadata; failures
leave no new route. The summary names actions and durations, and distinguishes movement,
stationary or absent players, and empty input coverage. The harness clock and recorder continue
through game pauses. Existing game files, app, store and verify/vision modules are untouched.

## What was run

The required fetch of `c169a5e0da304773587304ed47bc8aabcec80da7` completed before the baseline.
Base: current main `ccc54d5f9d9bd99d688e720d54185077921e6be5`.

- Before: `python3 -m unittest discover -s tests -t .`: 3,002 tests; 3 failures, 2 errors,
  31 skipped.
- After: the same command: 3,027 tests; 3 failures, 2 errors, 35 skipped.
  The exact 5 failing names and types are unchanged; no new failures. Full logs and
  the machine-readable comparison are included in the handover. The suite is not green.
- `python3 -m unittest tests.test_auto_route -v`: 21 offline tests passed.
- `python3 -m unittest tests.test_auto_route tests.test_package -v`: 39 tests passed.
- `EXPECTRAIL_ENGINE_TESTS=required python3 -m unittest tests.test_auto_route_engine -v`: all
  4 passed on real Godot 4.7.2. Bundled game: 2,094 ticks; crate-run: 243 ticks; both produced
  three identical complete traces with horizontal player movement. Pause/resume kept the clock
  running while the player obeyed pause. An independently randomized source differed at ticks
  0–242 and produced no route.
- Installed-wheel probe outside the checkout, with standard-library Python and an offline replay:
  three replays and a saved route; passed. The reproducible probe is included in the handover.
- An attempted `tests.test_cli` invocation found no such test module; no product test ran in that invocation.

The unchanged failure names and types in both runs are:

- **ERROR** `setUpClass (tests.test_event_input.EventInputTest)`
- **ERROR** `test_a_real_fix_is_accepted_with_the_private_sessions_mounted (tests.test_web.FixLoopTest.test_a_real_fix_is_accepted_with_the_private_sessions_mounted)`
- **FAIL** `test_its_own_tests_pass_and_every_body_it_sent_is_in_the_contract (tests.test_runit_edge.EdgeFunctionTest.test_its_own_tests_pass_and_every_body_it_sent_is_in_the_contract)`
- **FAIL** `test_a_bug_its_checks_cannot_see_is_not_detected_without_sam (tests.test_web.FixLoopTest.test_a_bug_its_checks_cannot_see_is_not_detected_without_sam)`
- **FAIL** `test_without_the_private_sessions_nothing_is_accepted (tests.test_web.FixLoopTest.test_without_the_private_sessions_nothing_is_accepted)`

## Not done

Rendered-frame equivalence, native macOS and Windows, a recorder UI, player binding discovery,
and proof of determinism beyond these three replays. No paid models, commits, pushes or GitHub
writes. The architect must validate before pushing; the full suite is not claimed green here.

## Files

- `expectrail/cli.py`
- `expectrail/route.py`
- `harness/godot/expectrail_harness.gd`
- `setup.py`
- `contracts/examples/auto-route.json`
- `tests/test_auto_route.py`
- `tests/test_auto_route_engine.py`
- `docs/auto-route.md`
- `docs/new-work/2026-11-13-auto-route.md`

## Architect run (Linux, main 6577c5b7)
Applied with --3way: the harness hunk conflicted with #402, which had already made the harness keep running while the game pauses (the same `process_mode = PROCESS_MODE_ALWAYS`). Main's version was kept, so this change leaves the harness as main has it. Full suite: 3096 tests, OK, 31 skipped. `tests.test_auto_route tests.test_package` OK. `EXPECTRAIL_ENGINE_TESTS=required tests.test_auto_route_engine`: 4 OK with Godot 4.7.2. `check-installed-route.py`: PASS. By hand: the bundled game and crate-run each gave three identical traces, the player moved, and a route was written.
