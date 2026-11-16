# Measured boxes for configured Godot roles (#259)

## What changed

Configured Godot replays now emit `roleObjects` on every tick: role, stable instance ID,
world and screen bounds, engine visibility, and drawing/collision provenance. Bindings resolve each
tick, so spawned and replaced objects are recorded; a binding never found, an ambiguous selector or
unsupported geometry refuses the replay with a named setup error and no trace. The schema, example,
writer, observation reader, agreement references and replay-state comparison change together.

Configured observations use measured drawing bounds (or a labelled collision fallback), not the
bundled coin size or player-feet offset. Hidden and offscreen objects are omitted from observations;
the trace retains hidden geometry. Older configured traces still load but cannot invent missing
role measurements. Unconfigured legacy readers and traces retain their behaviour. The reproduction
reader's allowed field names include the new schema field. The wheel carries both new modules.

Two real-engine gaps were exposed: configured assets without checked-in `.import` mappings could
load with no texture, and a headless window could remain at 64 × 64. Configured replays now import
the staged project, and headless configured windows use the game's declared size. No unconfigured
import or window rule changed. These tests use public trusted fixtures with sandbox off.

## What was run

| Run | Tests | Failures | Errors | Skips | Seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full suite before | 4,058 | 0 | 0 | 48 | 417.846 |
| Full suite after | 4,066 | 0 | 0 | 49 | 396.468 |

Command: `python3 -m unittest discover -v -s tests -t .`, with live-model keys/cap,
required integration switches and Godot overrides unset. Before and after failing-name sets are
both `[]`; no new failures. The additional skip is the new real-role class's named missing-Godot
lookup in this default profile. Existing skip names/reasons are unchanged. The retained engine
was used explicitly for all 11 headless Godot tests (192.901 s, OK), including the audit's four
binding regressions. `logs/comparison.json` preserves every name and reason.

Offline regressions against the audit-only product, with the new tests/example, produced 12 failed
assertions (including schema subcases) and one error across eight tests. Seven methods did not pass;
one already passed. The final eight offline tests pass. `regression-tests-only.patch` and
`logs/red-offline-schema.log` reproduce the red state. The seven new real tests cover drawing and
collision bounds, camera coordinates, multiple group members, mirror/rotation, hidden components,
current animation frames and offsets, dynamic appearance/removal/replacement, missing/ambiguous
non-player bindings, unsupported geometry, and crate-run. See `tests/test_role_boxes.py`.

| Real configured replay | Recorded ticks | Viewport | Roles measured | Engine ground check |
| --- | ---: | --- | --- | --- |
| config-lane | 120 | 360 × 240 | coin, ground, player | pass (120 judged frames) |
| crate-run | 150 | 640 × 360 | player | pass (120 judged frames) |

The config-lane evidence uses a disposable copy with `coin: Lookalike` and `ground: Floor` bindings
in addition to its player. No fixture approval was added. Both runs also have nonzero player
movement. These are engine-check passes, not verification accepts without vision.

| Public bundled case | Before and after engine check | Frames judged | Identical trace SHA-256 |
| --- | --- | ---: | --- |
| smoke | pass | 120 | `3ae192deca6d1fae5fa6677da690058c8c0bcd6845653d379cf741900128c925` |
| combat | pass | 90 | `c6ed74cfd49dccfd8a66753ec3a56e9581978f87c685abfa96eeba48ab8cf60b` |
| bug | fail | 26 | `98720dbb6712fc55f05485495fdfec3e8e99c252688288b926e62c8523b2f215` |

Trace bytes, observation-document hashes and complete engine verdict documents are equal in all
three pairs. The clean checks pass and the fall-through check fails. Combat has a 90-frame route;
the table reports the unchanged standalone ground check, not a claim that a truncated window
can clear a gate. Existing recorded Run it decisions are covered by unchanged
`tests.test_runit.RecordedTest.test_recorded_answers_give_the_samples_their_decisions_and_ask_no_model`.
This is headless trace/decision parity, not rendered-image parity. `evidence/parity.json`, the raw
traces and `evidence/reproduce.py` are in the handover; the script can regenerate them.

Three earlier baseline attempts exhausted storage/file entries: 54 errors; 113 errors plus one
cache-count assertion; 152 errors. Every error was Errno 28. They are retained separately, including
all failing names. The cache-count assertion passed unchanged after cleanup. The successful baseline
was rerun with exactly the audit tree after removing completed synthetic PNG fixtures verified
against the public test generator. No held-out or fresh-* contents were read.

The first after run found two integration gaps: the reproduction field list and the test's two-script
inventory. `logs/after-integration-gaps.log` and its name comparison are retained. Both were fixed;
`logs/integration-fixes.log` and the final full suite above pass. No test was deleted or skipped.

## Not done

No live model, paid request, new approval, hosted CI dispatch, native macOS/Windows run,
or rendered-image comparison. No commits, pushes, comments or PR were made here. No change to
`expectrail/gate/verify.py`, `expectrail/anchored.py`, `game/platformer`, or `.github/`.

This is **Part of #259**, not a claim that the whole audit is closed. Scene/toolchain/viewport
mismatch enforcement, a config-driven bundled-game conversion, and runtime inspect remain separate
audit gaps. Supported role geometry is Sprite2D, AnimatedSprite2D, Polygon2D and enabled collision
shapes/polygons. Custom drawing, a bound TileMapLayer, and other canvases/viewports are not measured
by this implementation; unsupported geometry refuses rather than fabricating boxes. Engine
visibility does not prove pixels, alpha, occlusion or shader output. See `docs/role-boxes.md`.

## Files

- `agents/godot_roles.py`
- `agents/observations.py`
- `contracts/trace.schema.json`
- `contracts/examples/trace-role-boxes.json`
- `docs/project-config.md`
- `docs/role-boxes.md`
- `expectrail/repro/evidence.py`
- `harness/adapters.py`
- `harness/godot/expectrail_harness.gd`
- `harness/godot/expectrail_roles.gd`
- `harness/run.py`
- `setup.py`
- `tests/geometry_fixture.py`
- `tests/test_role_boxes.py`
- `tests/test_tree.py`
- `docs/new-work/2026-11-16-role-boxes.md`

The pending audit dependency and its files are documented in
[the preceding audit log](2026-11-15-project-audit.md). The handover lists both the combined files
and the role-only files.

Guard: test change intended (#259)

- `tests/test_role_boxes.py` is new: offline contract/reader checks and real headless fixtures;
  no existing assertion is relaxed.
- `tests/test_tree.py`: extend the explicit injected-script inventory from two to three, retaining
  the exact game-file equality and cache-exclusion assertions; add byte equality for every injected
  script, so the helper must actually be copied unchanged.
- `tests/geometry_fixture.py`: include the new harness script in the replay-cache identity. No
  assertion changes; changing that script can no longer reuse a stale geometry fixture.
- `tests/test_project_audit.py` and config-lane are unchanged audit dependencies, included as requested.
