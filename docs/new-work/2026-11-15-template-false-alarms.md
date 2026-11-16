# Foreground witnesses reduce public clean false alarms below 2% (#262)

## What changed

Reproduced the original 79/390 clean false alarms (20.26%) before changing the sensor.
Sean supplied the original handover; its frozen bank digest
`b01dfdeffd3522193ee820d379cd34d72f3570a2abcf88a88ac8afed02d2162a` was verified.
All six original summaries, alarm frame identities, scores and boxes reproduce exactly.
All 2,190 regenerated PNG hashes match the original manifests. Every trace row matches;
main added only empty `unknownActions` metadata. The audit stops on disagreement.

The cause was whole-collision-crop luminance matching: background trees, sky and
terrain changed while the correct robot remained visible. Border/grid tuning alone
was inadequate. A 10% inset with floor 0.90 reached 45/390 but lost seeded alarms;
8/12 grids also lost seeds; 32 worsened clean validation. The earlier conservative
inset/0.93 profile reached 64/390 (16.41%), with old alarms retained. It remains an
explicit legacy profile, superseded by the new foreground measurement.

Added opt-in `expectrail.template-foreground/v3`: trusted RGBA art supplies the palette
for masks on clean training pixels; masked NCC proposes locations and full-resolution
RGB/whole-foreground/four-part coverage confirms them. Masks, RGB, configuration and
sources are frozen and checked by the reader. No temporal filling suppresses a missing
frame. Optional caller-selected clean pose catalogues register sprite-sheet scale and
translation on a clean capture, then freeze RGBA bytes and reconstructible pose/anchor
proof. Poses derived from art are labelled as such. Candidate pixels never train,
select masks/templates, adjust thresholds or register poses.

Fall-through revealed an important label error: its player is visibly drawn below the
floor, not absent. Added a separate benchmark reference-map crossing check, using
observed player boxes/camera against clean calibration `levelSurfaces`, with the public
20 px tolerance. Candidate body/ground/surface rows do not supply that reference.
Crossing requires continuous horizontal overlap and known pixels; losing evidence or
leaving a region resets history. Missing proof remains unavailable. This is not
candidate-ground segmentation, and it is not integrated into a default verdict.

New bank/measurement versions, observations extensions and the catalogue ship with
schemas, synthetic examples, writers and readers. Existing v2 banks still reproduce.
`--reuse-captures` verifies game, route, ordered patch, trace and every PNG before
independent copies; it calls no engine and reuses no observations/checkpoints. Resume
identities include foreground implementation hashes. The sensor stays opt-in.

## What was run

Base `7ed6106a1ef49e990282979963d950b0f8bc86fb`; branch `chatgpt/262-false-alarms`.
Read AGENTS.md; its required pinned fetch was performed once in the shared repository.
Linux, official SHA-512-verified Godot 4.7.2, software rendering, private dummy Xorg,
NumPy 2.3.5 and Pillow 13.0.0 regenerated the original frames. Measurements use one
BLAS/OpenMP thread and exact saved PNGs. No model or private held-out content was used.

Recorded foreground result: **0/390 clean alarms (0.00%)**, down from 79/390. All
390 clean frames match and have available region evidence. Invisible-player 77/120
versus 73/120, retaining every original 73 and all 49 paired pixel-only detections;
sinking 120/120 retained. Fall-through has 17 visible on-screen player detections,
12 correct region crossings at frames 5–16, and 103 off-screen unknowns. Its original
17 absence labels were wrong; no claim is made that they were 17 true absences.
All three seeded cases remain detected using the appropriate presence/position rule.

The 408-template bank uses 1,080 clean training frames, 342 captured appearances and
66 catalogue pose/mirror entries. Separate clean validation: 358/360 positive matches,
0/360 off-player negative matches, threshold 0.90, calibration `met`. Captured masks
alone gave 347/360; trusted-art poses improved coverage without candidate learning.
The bank digest is `a40e0e0e49d729eaeb6e58b3686e0102e2573f6407d2f4ddc1a0de1afd515eb8`.
These are public tuning results, not independent held-out or cross-game validation.

`python3 -m unittest discover -s tests -t .` passed **3,767 tests, 42 skipped**,
in 374.632 seconds, with no `EXPECTRAIL_*` variables in the shell. All 69 focused
sensor tests pass. Blocking Pillow imports, or both Pillow and NumPy imports, gives
69 tests with 44 named imaging skips and 25 passing metadata/region tests. The named
skip reasons identify Pillow; no test was deleted or weakened.

`git diff --check`, compile checks and contract-reader checks passed. The patch applies
cleanly to fetched main `ccb58ef2105c707666c80334044dbae448b56320`. ZIP member hashes
and CRCs were checked against the staged source and the packaged SHA256SUMS manifest.
An earlier 3,766-test suite also passed before the final region-history edge-case test;
the final run above includes that test and its implementation.

Guard: test change intended (#262)

Existing assertions are unchanged. The legacy shared fixture explicitly requests its
original 0.90 floor so its original behavioral assertions remain applicable.

## Not done

The maximum 0.3-second/frame speed target remains unmet; the benchmark exits 2 on
that target failure and keeps results. Timing includes contention from full-suite
work. No default verdict integration or claim of general reliability is made.
Palette collisions, lighting, occlusion, unseen poses and other games need independent
validation. Frozen floor regions cannot certify moved/removed ground, a player already
below terrain on the first frame, unsupported cameras or gaps without pixel evidence.
No source-game, approval, workflow, orchestrator or CLI change was made. No push, PR,
GitHub comment, repository creation or workflow dispatch was performed.

## Files

- `agents/template_observations.py`, `agents/template_sensor_bench.py`
- `agents/template_foreground.py`, `agents/template_art.py`, `agents/template_regions.py`
- sensor contracts and their foreground/catalogue synthetic examples
- `tests/test_template_sensor.py`, `tests/test_template_sensor_sampling.py`, `tests/test_template_foreground.py`
- `docs/template-sensor.md`, `docs/template-sensor-measurement.md`, `docs/template-sensor-measurement.json`
- this work log
