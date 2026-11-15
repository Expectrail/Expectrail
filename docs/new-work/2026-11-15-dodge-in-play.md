# Judge Dodge's play area while its player is in play (#263, PR #473)

## What changed

The outside trial on `86969724bec01163c1471d4ad496ffa101da6824`
([run 43697368130](https://github.com/Expectrail/Expectrail/actions/runs/43697368130))
rejected the pinned, harmless and broken games. Its findings show a real 54×68
player body, while the region audit had omitted `body` and used the bundled
40×60 fallback. The gate converted the real origin to `[-27,-54.75,27,13.25]`,
outside the spec's `[-20,-46.75,500,733.25]` even at a legal edge.

The pinned game's `player.gd` hides the node in `_ready()`, shows and positions it
in `start()`, and hides it on a hit. `main.gd` starts it at `[240,450]` in
`new_game()`. The existing route really starts that round at tick 10; its start
action was not missing. Its full 300 ticks and all movement actions are unchanged.

The audit now requires a measured, visible clean player body at native view size;
it refuses missing or inconsistent measurements. The corrected converted region
is `[-27,-54.75,507,733.25]`. The global box conversion (including its existing
feet offset) is unchanged: the same conversion is used on both sides of this
origin/bounds check. No tolerance is added. One-pixel escapes still fail.

An optional `coverage.whenPlayerVisible` condition uses the new optional
`playerVisible` trace field (Godot node visibility in the tree, not pixel proof).
The evaluator lists hidden frames as not exercised and unknown visibility as
insufficient observation. A visible counterexample still fails. Entirely hidden
runs cannot pass. Existing specs without this opt-in retain their behavior.
The gate passes the capture rate to this filter so frame/tick alignment remains
correct at other rates. Complete-window and complete-route checks remain intact.

Dodge requires at least 120 judged frames (two seconds at its 60 fps, matching the
round's initial two-second delay before enemy spawning). Hiding almost the whole
run therefore cannot satisfy this check. The spec changed and its old approval
was REMOVED. Sean must review and approve the new content himself. No approval
was created, including for the diagnostic replays.

## What was run

Read the branch's AGENTS.md, PR #473 and its discussion; preserved the Architect's
per-project spec selection, viewport audit, patches, manifest and the unchanged
kinematic-character check. Fetched the required historical commit and the branch;
worked on its exact head `86969724bec01163c1471d4ad496ffa101da6824`.

The unchanged full suite passed: 3,534 tests in 322.588s, 46 skips, no failures or
errors. Three targeted regression probes failed on the old head (two failures,
one error) and all three passed after the change. Focused final checks: 123 tests in
7.618s, OK (one existing engine-prerequisite skip). The final full suite passed: 3,541 tests in 392.612s, 46 skips,
no failures or errors. Both failing-name lists are empty; skip names and reasons
are identical. Full logs and the comparison are in the handover.

Real-engine results and exact commands are in the handover's `replay-check.py`,
`logs/real-replays.log` and `evidence/replays/results.json`. Replays use the
SHA-512-checked Godot 4.7.2 download and a local virtual display. They capture all
300 frames on each run. The pinned public source tree is checked against its
recorded digest before calibration, and the broken/harmless patches are applied
only to replay copies. All three pinned and all three harmless runs pass the engine check, judging 183
frames and marking 117 hidden frames not exercised (0–9 and 193–299). Each gives
needs-review under the shared rule without vision. All three broken runs fail at
frame/tick 97: origin `[486.666,450]`, converted right edge `513.666`, region right
edge `507`. They give reject under that same rule. The broken run judges 242
frames and marks 58 not exercised. Each variant's three complete trace files are
byte-identical. Images at frames 0, 10 and 193 were inspected: start screen without
the player, player shown, then game over without the player.

The diagnostic runs call the actual evaluator and shared
gate rule without a visual observer. They do not bypass the approval requirement
of `expectrail verify`; their reported decision is explicitly `decisionIfApproved`.

An initial baseline attempt exhausted disk during a source fetch (one failure,
657 errors, 43 skips). Its log is retained, not treated as a product regression.
The successful baseline was rerun before edits. Only identified completed
synthetic fixture output and six ignored, byte-identical engine download caches
were removed; one verified engine download was retained. No test was skipped or
weakened to make space. The first after run found one missing reader update:
`tests.test_repro_evidence.ForAProposer.test_the_fields_it_may_name_are_the_trace_rows_own`.
The reproduction report's trace-field allowlist now includes `playerVisible`;
that test is unchanged. The first after log is retained separately. No paid model, dispatch, commit, push or GitHub write.

## Not done

Sean's new approval and a subsequent approval-enforcing outside-trial run remain
required. Diagnostic decisions on the draft are not a release clearance.
No vision ran. No claim of visual correctness or verified outside-project status.
The local engine replays use the explicitly recorded sandbox `off` mode because
this container refuses the required bubblewrap namespace; CI must rerun them
with the sandbox required. No macOS run. The visibility condition is lifecycle
state only; it cannot prove that a sprite is drawn, and does not replace vision.
A spatial check conditional on being in play does not judge hidden intervals.

## Files

- `contracts/test-spec.schema.json`, `contracts/trace.schema.json`,
  `contracts/verdict.schema.json`: optional lifecycle condition, trace field and
  explicit not-exercised/unknown frame lists.
- `contracts/examples/test-spec-player-visibility.json`,
  `contracts/examples/trace-player-visibility.json`,
  `contracts/examples/verdict-player-visibility.json`: unapproved examples.
- `harness/godot/expectrail_harness.gd`: record node visibility.
- `expectrail/repro/evidence.py`: include the new trace field in its existing reader allowlist.
- `expectrail/evaluator.py`, `expectrail/gate/verify.py`: filter opt-in frames,
  retain evidence digests and coverage, carry the capture rate.
- `tools/dodge_play_area.py`: require actual clean body measurements.
- `tests/outside/specs/dodge-play-area.json`: corrected region, lifecycle condition,
  minimum exercised frames, old approval removed.
- `tests/test_dodge_check.py`: real body fixture, unchanged boundary assertions,
  lifecycle/coverage/gate regressions.
- This work log.
