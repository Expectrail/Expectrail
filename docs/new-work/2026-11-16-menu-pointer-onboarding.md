# Start menu-first pointer games from their own scene (#259)

## What changed

Completed menu and pointer-route generation on top of the earlier route contract.
Static inspection names pointer hints; an opt-in live engine probe reports buttons,
geometry, visibility, enabled state and pressed connections. Ambiguous/control-only
plans refuse plainly. The generated route clicks the measured control and sweeps
the viewport. Auto-route requires three identical traces and bound-player movement;
`init` remains a draft. Saved draft review stays offline. Contracts, example,
writer/reader and bundled-module packaging are changed together.

The same-pin [Breakout retrial](../outside-trials/breakout-pointer/report.md) starts
play and moves the paddle without core changes during the trial. Three rendered
traces are byte-identical; harmless matches pinned. Both raw draft diagnostics pass
on pinned/harmless, while the broken paddle fails its bounds window at frame 20.
All three CLI jobs remain needs-review with zero approved checks run. No approval
or vision run was made. The historical failed trial remains unchanged.

## What was run

Before: **4300 tests, 450.780s, 0 failures, 0 errors, 53 skips**. Final after: **4313 tests, 408.599s, 0 failures, 0 errors, 54 skips**. Failing test names: `[]` → `[]`; no new failing names.

[Logs and failing-name comparison](../menu-routes-evidence/README.md) retain the
first after-run error (JSONDecodeError in an unchanged ingest-repair test), its
passing isolated rerun, and the final full run. The preceding pointer-contract
final suite is reused as the before baseline. No product/test change was made
between the failed after run and its reruns; the transient cause is not diagnosed.

New tests first fail on missing probe/planner behavior (red: 10 tests, 1 failure,
8 errors). Green: 39 menu/pointer/event tests pass; final menu set: 16 pass with
Godot 4.7.2; related set: 90 tests pass, one prerequisite skip. Real headless menu
and pointer-only fixtures replay three times and compare bytes and movement. The
import blocker proves the new logic loads without NumPy/Pillow.

[Eight legacy rendered pairs](../menu-routes-evidence/parity-comparison.json)
preserve trace bytes, coverage, reasons, decisions and first failing frames.
Bundled/kinematic/Dodge broken copies still reject at frames 5/44/97; pinned and
harmless engine passes remain needs-review without vision. No sandbox isolation
claim. Breakout's [numbered command log](../outside-trials/breakout-pointer/commands.md)
includes machine timings, every stop, draft diagnostics and source/core checksums.

## Not done

No live model, approval, outside accept, native macOS/Windows, arbitrary menu
semantics/translations, subviewport/touch/wheel support or human timing. Breakout's
repository-root registry refusal remains; it was not added to the outside list.
Pointer explanations still print every event. Both are recorded issue texts, not
core fixes made during the frozen trial. Sean must review any draft approval.
No GitHub writes, commits or pushes.

## Files

- `contracts/trace.schema.json`, `contracts/examples/trace-input-probe.json`.
- `harness/run.py`, `harness/godot/expectrail_harness.gd` (probe opt-in only).
- `expectrail/input_discovery.py`, `onboarding.py`, `onboard.py`, `route.py`, `setup.py`.
- `tests/test_menu_routes.py`, `tests/projects/pointer-paddle/`, `tests/outside/breakout-pointer/`.
- `docs/pointer-routes.md`, `docs/outside-projects.md`, `docs/menu-routes-evidence/`,
  `docs/outside-trials/breakout-pointer/`, this log.

No gate/anchored, workflow, source game or approved spec edits in this continuation.
Earlier Part A and pointer-contract dependencies are separately identified in the
handover; their historical work logs are not rewritten.
