# Template sensor false-alarm follow-up (#262)

**Clean false alarms fell from 79/390 (20.26%) to 0/390 (0.00%) on the same public
frames. All three seeded bugs are detected.** The sensor remains opt-in, with no
default verdict change. These are public tuning results, not held-out validation.

| Public corpus metric | Before: whole-crop luminance | After: foreground witnesses + clean region reference |
| --- | --- | --- |
| Clean false alarms | 79/390 (20.26%) | 0/390 (0.00%) |
| Invisible-player detection | 73/120 absence alarms | 77/120 absence alarms; all original 73 retained |
| Sinking detection | 120/120 absence alarms | 120/120 absence alarms; all retained |
| Fall-through detection | 17/17 absence alarms (misclassified visible pixels) | 12 position-crossing frames (5–16); player visible in all 17 on-screen frames |

Smoke, combat and traversal each have zero clean alarms, with all 390 frames measured
and all clean region proofs available. No unknown or off-screen evidence was
reclassified to improve the denominator. All **49 paired pixel-only detections**
remain detected: the original clean frame matched but its hidden-player counterpart
with the same engine trace did not. Four extra invisible-player alarms are at frames
38, 60, 61 and 72; these are not independently labelled additional true positives.
That fixture changes draw order (`z_index = -6`), so the player can still appear
where scenery does not cover it; 77/120 is an alarm count, not an absence-recall score.

Fall-through requires a different predicate. Diagnostic images show the robot still
drawn below the floor; the old absence alarms came from mismatched background. The
new detector locates that robot in all 17 on-screen frames. Its observed pixel box
crosses a frozen clean ground boundary beyond the existing 20 px tolerance at frames
5–16. Frames 0–4 remain within tolerance. The other 103 predictions are off screen
and remain unknown for region checks. Claiming 17 retained true absence detections
would be wrong. Case-level detection is retained with the correct position check;
these counts are not an independently labelled frame-level recall estimate.

## Reproduction and diagnosis before changing the detector

The unchanged baseline first reproduced the published 79/390. Sean's original
handover then verified the exact frozen bank
`b01dfdeffd3522193ee820d379cd34d72f3570a2abcf88a88ac8afed02d2162a`.
All **2,190 regenerated PNG hashes** match its full replay manifests. Every trace row
matches; the only trace difference is main's new empty `unknownActions` metadata.
Re-running that original bank reproduces all six summaries, alarm indices, scores
and boxes exactly. The handover includes the original ZIP and an audit that stops
on a bank, PNG, trace or summary mismatch.

Every original clean alarm was `not-found`, with no unavailable or displaced frames.
Diagnostic crops showed the correct robot pose and location amid different trees,
sky and terrain inside the collision-box rectangle. Whole-crop luminance correlation
penalized background changes. Cropping borders and changing grid sizes reduced some
alarms but either lost seeded alarms or stayed far above 2%. The earlier 0.93 core
profile reached only 64/390 (16.41%); it is superseded by the foreground result here.

## Change and separate clean validation

`expectrail.template-foreground/v3` freezes RGB foreground masks from trusted clean
art and captures. Masked luminance NCC proposes locations; full-resolution RGB and
four-part foreground coverage confirm them. Changing background is excluded by the
clean masks. Missing evidence is not filled from neighbouring frames.

The supplied optional pose catalogue adds declared clean sprite-sheet poses absent
from captured training routes. It pins scene and art provenance, registers scale
and translation on a clean capture at at least 98% foreground agreement, and freezes
the RGBA bytes and registration proof. Derived entries are identified as art poses,
not captured examples. Readers reconstruct their bytes and check the clean anchor.
No hardcoded player dimensions or sprite/body offset is used. For this clean asset,
registration finds pose 30 at scale 2, offset [21,10], with exact foreground agreement.

The frozen bank has **408 templates** (342 clean-capture appearances and 66 derived
pose/mirror entries), digest
`a40e0e0e49d729eaeb6e58b3686e0102e2573f6407d2f4ddc1a0de1afd515eb8`.
Three dedicated clean training routes contribute 1,080 eligible frames. The separate
clean validation route has **358/360 positive matches (0.56% missed)** and **0/360
off-player negative matches**, at threshold 0.90; calibration status is `met`.
Captured masks alone gave 347/360 positive validation matches; adding clean art poses
covered most missing jump-and-fire appearances. Measured/seeded pixels never enter
templates, masks, thresholds or registration. Algorithm development used public
regression results, so separate calibration routes do not make these held-out results.

Ground checks use observed player pixels and the camera against `levelSurfaces`
frozen from clean calibration. Candidate body/ground/surface rows do not establish
the boundary. Crossing requires an above-boundary observation followed by a below
observation while overlap continues. Leaving the region or losing pixel/camera
evidence resets that history; walking under an overhead platform does not arm it.
The reader recomputes crossings from stored pixel-box/camera proof. This is a clean
reference map, **not current-ground segmentation**: it cannot certify moved/removed
floors, spawn-under-terrain or gaps without evidence.

## Evidence, timing and limits

Linux, official Godot 4.7.2 (repository SHA-512 verified), NumPy 2.3.5, Pillow 13.0.0,
software rendering and a private Xorg dummy display regenerated the frames. Clean
tree: `6a273587d64e10a74c0160256cfdc4964f16ed3e93fe7ab178e1bedc5071b280`.
Measurements reuse those verified PNGs with one BLAS/OpenMP thread. Bank/capture,
full observation/trace/replay records, timing report, diagnostics and audit scripts
are in the handover. Sample PNGs are retained there; the complete frame set is
regenerated with the pinned engine and checked against original hashes.

The under-2% and 95%-per-clean-route accuracy targets are met. The earlier maximum
0.3-second/frame timing target remains **unmet**; the command intentionally exits 2
and preserves evidence when that target fails. Full-suite work shared CPU with
measurement, so timings include contention. The compact numerical summary is
[template-sensor-measurement.json](template-sensor-measurement.json).

Under 2% is demonstrated on this public corpus. Broader validation remains open:
palette collisions, lighting, partial occlusion, unseen poses and other projects
can still fail. Local engine predictions are search hints, not visibility truth.
Scores are similarities, not probabilities, and a matched rectangle does not certify
all sprite pixels or semantic identity. No default verdict integration, live model
call, private held-out material, approval, workflow or source-game edit was used.
