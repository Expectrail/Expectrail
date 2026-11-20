# Viewport pointer events in the route contract (#259, first half)

## What changed

Added pointer move/button events to the existing route array, preserving named
actions. Contracts and examples, Godot delivery, normalized episode inputs and
all action-assuming readers are updated together. Unsupported Unity/catalog paths
refuse instead of dropping input. A menu/paddle fixture covers pointer queries
in headless and scaled rendered windows. See [format and limits](../pointer-routes.md).

## What was run

Before: **4287 tests, 459.696s, 0 failures, 0 errors, 51 skips**. After: **4300 tests, 450.780s, 0 failures, 0 errors, 53 skips**. Failing test names: `[]` → `[]`.

[Full logs and comparison](../pointer-routes-evidence/README.md) are published.
All 17 pointer tests passed with Godot 4.7.2/Xvfb, including three identical traces
per display mode; 133 related tests passed with one named prerequisite skip.
New test classes skip by name without the pinned engine; their actual engine run
has no skips. Tests load with NumPy/Pillow blocked. Red logs cover old behavior.
The corrected preflight red restores the prerequisite runner and keeps the same
assertions. The full suite caught two input dispatch call sites; both now share
one dispatcher, and the existing guard remains unchanged. Initial disk/display/test-path setup failures are retained in the
handover and distinguished from the passing final runs.

Eight legacy before/after captures preserve byte-identical traces and decisions:

| Case | Engine before / after | Decision before / after | First failing frame | Trace bytes |
| --- | --- | --- | --- | --- |
| bundled-pinned | pass / pass | needs-review / needs-review | none | identical |
| bundled-broken | fail / fail | reject / reject | 5 | identical |
| kinematic-character-pinned | pass / pass | needs-review / needs-review | none | identical |
| kinematic-character-harmless | pass / pass | needs-review / needs-review | none | identical |
| kinematic-character-broken | fail / fail | reject / reject | 44 | identical |
| dodge-the-creeps-pinned | pass / pass | needs-review / needs-review | none | identical |
| dodge-the-creeps-harmless | pass / pass | needs-review / needs-review | none | identical |
| dodge-the-creeps-broken | fail / fail | reject / reject | 97 | identical |

[Machine-readable comparison](../pointer-routes-evidence/parity-comparison.json)
links each trace/finding. Sandbox off; no vision/model/key; no new accept claimed.

## Not done

This is the separately deliverable route-contract half. Engine-based menu
selection, pointer inspection/auto-route generation and the same-pin Breakout
retrial are not done. No approval was written. No native macOS/Windows, Unity
player build, wheel/touch or subviewport support was tested or implemented.

## Files

- `contracts/route.schema.json`, embedded `playtest-report.v1.schema.json`,
  `episode.v1.schema.json` and the new route/episode pointer examples.
- `harness/godot/expectrail_harness.gd`, `harness/run.py`, Unity runner and direct
  entry/DTOs: deliver pointers in Godot and explicitly refuse them in Unity.
- `expectrail/route.py`, `onboard.py`, `trace/normalize.py`, `trace/evaluator.py`,
  `repro/reach.py`, `jit/run.py`, `tools/playtester/producer.py`: preserve pointer
  input or retain explicitly named-action-only behavior without crashes.
- `tests/test_pointer_routes.py`, `tests/projects/pointer-menu/`.
- `docs/pointer-routes.md`, `docs/pointer-routes-evidence/`, this work log.

Prerequisite changes are separate in the handover's dependency patch. Protected
gate/observer files, workflows, game sources and approvals remain unchanged.
