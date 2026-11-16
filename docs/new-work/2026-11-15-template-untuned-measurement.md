# Frozen sensor on new public frames (#262)

## Plan written before new captures or measurements

This section is fixed before any new capture, pixel inspection, template calibration
for the outside project, or sensor measurement. It will be retained verbatim; results
are appended below. Task branch `chatgpt/262-untuned-measure` started from main
`3063a8249bae50e1d2ab8313182925a1f8ee83c8`. PR #522 head
`cfb9c9c171d0a433c92732bffb0a39370a83431a` is applied locally as prerequisite
`5e67e66`; its sensor/reader/schema files are frozen byte for byte, not edited here.

### Fixed sensor and original bank

Use `expectrail.template-foreground/v3` exactly from #522, the same default settings,
and the exact original 408-template platformer bank from its handover:
canonical digest `a40e0e0e49d729eaeb6e58b3686e0102e2573f6407d2f4ddc1a0de1afd515eb8`,
raw SHA-256 `6d646efd35e96306d10ac7e7ab615c2ee63a3d606e95d8a4d441adf7a7d60235`.
No recalibration, threshold/code/bank edits, template additions or pose selection
will follow evaluation. Hashes are checked before and after each stage. If a frozen
component is changed, the affected frames become tuning data; they cannot support
an untuned claim and replacement evaluation data would need a new plan.

### Source A: bundled platformer, unchanged art and frozen original bank

Use ALL frames at 60 capture fps from:

- Existing public `harness/routes/coins.json`: 240 physics ticks, seed 1, 120 frames.
  Prior #262 used smoke/combat/traversal plus cal-walk/cal-air/cal-fire/cal-validation;
  coins was not among those captures, template sources or tuning experiments.
- New `sensor-untuned-platformer-v1`: 720 ticks, seed 26220261115, 360 frames. Events:
  right on 17/off 183; jump on 53/off 65 and on 111/off 123; shoot on 71/off 77
  and on 143/off 149; left on 211/off 371; jump on 247/off 259; shoot on 289/off 295;
  right on 403/off 567; jump on 439/off 451; shoot on 491/off 497. No other events.
  This action timing/seed has never been captured or used to build the frozen bank.

For both routes also capture the three existing seeded variants used by #522:
fall-through patch alone; sinking v2; and fall-through plus fix-but-hide-player.
Those are secondary bug measurements with the SAME frozen bank, not calibration.

### Source B: public kinematic-character, different art

Use only the pinned public project listed in `tests/outside/projects.json`:
`godotengine/godot-demo-projects`, commit
`b761b4cd5718a7118f2c95eb55f181d0a5f004f1`, `2d/kinematic_character` (MIT).
No outside frames or art entered #522's tuning or robot bank. Do not read its vision
recording; this task needs no model or recorded model answers.

Evaluation is ALL 180 frames of the existing public
`tests/outside/kinematic-character/routes/walk.json` (360 ticks, seed 1) plus ALL
360 frames of new `sensor-untuned-kinematic-v1` (720 ticks, seed 26220261116):
right on 13/off 193; jumps on 67/off 79 and on 137/off 149; left on 227/off 407;
jump on 281/off 293; right on 443/off 623; jump on 497/off 509; no other events.
Capture both existing seeded changes (`broken.patch`, `invisible.patch`) on both
routes. The harmless tint is an optional behaviour change, not a seeded bug here,
and is not measured. No evaluation action/seed will be changed after capture.

Predeclare TWO bank arms, reported separately: unchanged robot bank (cross-art
transfer, presence only; its platformer floor map is not applicable to this project),
and a project-specific bank. The latter is expected to be necessary for different art.
It must be built/frozen BEFORE evaluation captures from separate clean calibration:

- 720 ticks, seed 262889101: right 41–281, left 337–577, no jumps.
- 720 ticks, seed 262889102: right 29–269, left 319–559; jumps 83–95, 173–185,
  373–385, 463–475.
- 720 ticks, seed 262889103: left 23–203, right 257–557; jumps 61–73, 151–163,
  307–319, 397–409, 487–499.
- Separate validation: 720 ticks, seed 262889104: right 37–277, left 323–563;
  jumps 97–109, 187–199, 383–395, 473–485.

Use the clean player Sprite2D texture referenced in the pinned scene as the single
foreground art asset, with no extra pose catalogue. Use #522's calibration algorithm
and its unmodified default configuration, including its automatic validation-only
threshold rule. No manual threshold changes, crop fixes or parameter overrides.
If calibration cannot produce a bank, report that source/arm as unavailable, without
changing the sensor or silently dropping the source. The original robot-bank arm
still runs. The outside bank is a separate row, never claimed as zero-shot transfer.

### Predeclared counts, exclusions and ordering

Capture/calibrate the outside training and validation routes first, freeze its bank,
then capture evaluation. The original robot bank is already frozen. No evaluation
frame enters either bank. Use the pinned Godot 4.7.2 binary, software rendering,
NumPy 2.3.5/Pillow 13.0.0 and one BLAS/OpenMP thread, as in #522.

Some identical idle images can occur on different routes. For the primary *new-pixel*
rate, exclude PNG hashes appearing in ANY of the prior #262's 2,190 training,
validation, clean or seeded frames. For outside own-bank rows also exclude hashes
from its separate training/validation captures. This hash-only rule is fixed now;
it is not based on scores or image inspection. Report raw full-route counts and
excluded counts too. New evaluation frames may repeat each other; frame rates are
not a claim of statistically independent samples. Do not relabel or drop failures.

False alarms are the union of presence disagreements (`not-found`/`displaced`) and
applicable frozen-clean-reference crossings, counted once per clean frame. Report
presence and crossing counts separately as well. Missing/off-screen evidence stays
unknown, with explicit counts; no source passes the under-2% bar with incomplete
clean evidence. Region proofs for hash-excluded frames use unknown boxes to avoid
arming region history from excluded frames. Full raw observations are retained.
The robot-bank outside arm reports presence only and explicitly no applicable floor
reference. Seed detections use absence for hidden/sinking and position crossings
for fall-through/broken, as #522, with unsupported/unknown cases stated plainly.

No sensor correction, retuning, new template pose or evaluation-route alteration
will follow results. Any percentage is a valid finding for this task. Under 2% on
new frames is the later verdict-consideration bar, not permission to wire this into
a verdict. The sensor remains opt-in. No live model call or private/held-out/fresh
content will be used. No push, PR, GitHub comment or workflow dispatch is authorized.

## What changed

Measurement routes, reproducible measurement/report tooling and documentation only.
PR #522's sensor and original bank remain unchanged. Results follow the frozen plan.

## What was run

Not yet measured at the time this plan was written. Results and validation will be
appended after freezing inputs and running the planned captures.

## Not done

No claim of verdict readiness, private held-out validation or cross-game zero-shot
accuracy. No default observer or verdict integration.

## Files

This work log; the measurement routes, runner, result and report added by this task.

## Completed results (appended after the fixed plan)

The exact planned source/seed/action selections were used. Platformer: 8/438 new-pixel
clean false alarms (1.83%), pooling coins 0/97 with the new route 8/341 (2.35%). Raw
counts are 8/480 (1.67%). The outside robot-bank arm alarms on 540/540 clean frames
(100%); it has no applicable platformer-floor reference. A separately calibrated
outside bank is unavailable: its 16×16 player art is fully opaque, and the unchanged
foreground builder requires transparent background. All 1,440 separate calibration
frames were captured before evaluation, but no bank/threshold was created. No workaround
or retuning was performed. The two-source under-2% bar is NOT demonstrated.

Seeded results are tabulated in docs/template-sensor-untuned-measurement.md. Paired new-pixel
counts are hidden 57 and sinking 97 on coins, hidden 261 and sinking 333 on the new route.
Fall-through still gives 12 raw crossings on each route; coins has no novel candidate
frames, and the new route has 3 novel crossings but no novel matched clean counterparts
at those indices. Outside invisible alarms do not discriminate from clean (540 clean
alarms, zero matched-clean pairs); broken position checks are unsupported. Off-screen
frames are explicit unknowns, never positive or negative pixel evidence.

The sensor/contract bytes match PR #522 and the original bank's raw/canonical hashes
before and after measurement. The plan snapshot is retained verbatim. One runner API
keyword was corrected after an argument-binding TypeError, BEFORE any evaluation PNG
was opened or score produced; source sensor/bank/threshold/route files did not change.
Both execution manifests and the stop log are retained. All subsequent runner hashes
remain unchanged. No result-dependent code change was made.

Final full suite on the corrected runner: 3,954 tests OK, 45 skipped, 445.072 seconds,
with no EXPECTRAIL_* shell variables. Four bookkeeping/signature tests pass. A prior
3,953-test run began before that wrapper correction and is not the final validation.
The evidence audit verifies all 4,980 raw PNG hashes plus the observation contracts,
exclusion counts, rates, seeded pairings and reference proofs. Full raw-frame data is
retained losslessly, separate from the compact handover ZIP; sharing status is recorded
in its README. Freeze, compile and patch-application checks are recorded in validation.

The sensor remains opt-in. These public results do not establish verdict readiness.
Supporting the outside asset or fixing shooting-transition misses is future tuning;
if these findings inform a change, new evaluation frames are needed. No live model,
fresh/blind/private held-out content, source-game edit, approval or workflow change.

### Actual files added

- tools/template_untuned_measure.py (measurement arithmetic/orchestration, not sensor code)
- tests/test_template_untuned_measure.py; six predeclared route JSONs under tests/fixtures/template-untuned/routes/
- docs/measurements/template-untuned-freeze.json, template-untuned-execution-freeze.json, template-untuned-result.json
- docs/template-sensor-untuned-measurement.md and this work log
