# Diagnose a player not drawn at its place (#330)

## What changed

AnchoredObserver compares each scored answer's width and height, converted to game pixels, with the clean calibration's drawnSize. It reuses the calibration's sizeTolerance and sizeFloorPx through the existing comparison function: 25% or 4 pixels, whichever is larger. A different-sized answer is retained under notDrawn with its raw box, score, expected/measured sizes, prompt point, scale and thresholds; it is not emitted as a player detection. A successful empty response is also explicit negative presence evidence. Provider/parse errors and answers without confidence remain uncertainty.

The observations schema and a synthetic example define this optional evidence. The evaluator reads it as a counterexample, retains frame evidence, and reports how many observed frames did not show the calibrated player at its place. Size-mismatch evidence still obeys the spec's confidence floor. Ordinary empty detections remain needs-review. The gate already rejects a visual failure, so no gate change was needed. The old hidden-player test now asserts fail, a stronger outcome. No calibration rule or approved spec changed.

## What was run

- Required fetch of c169a5e0da304773587304ed47bc8aabcec80da7, then origin/main; base 2e7caa06f1b9f1962dbd4c7f67fdbe32d86e594c.
- Full unittest discovery before and after, using the included run-suite.py to clear live model keys/cap and optional integration switches. Before: 3568 tests, 0 failures, 0 errors, 46 skips, 324.007 seconds. After: 3574 tests, 0 failures, 0 errors, 46 skips, 346.001 seconds. Failure/error-name sets are both empty; comparison and raw logs are in the handover.
- Focused anchored observer, outside vision, evaluator and contract tests: 59 tests, OK. The new full outside judge regression keeps pinned and harmless accept, broken reject and invisible reject, for both background-region and empty answers. Both recordings replay identical findings with no model constructed. The existing tiles-fail-calibration test still passes.
- Scaled captures, both size axes, exact 4-pixel and 25% boundaries, window/object scope, low confidence, missing confidence, provider errors, and a counterexample in a truncated window are covered. The schema accepts the new example and refuses malformed evidence.
- One initial focused attempt failed because fractional movement in the new exact-boundary fixture introduced floating-point drift during calibration. Fixed that fixture to use an exactly representable stationary position; no rule or assertion was loosened. The failed log is retained.
- git diff --check; patch application against the named base and byte comparison; ZIP checksums. No commits or pushes.

## Not done

#478 was open and unmerged when this task started; docs/outside-projects.md is therefore unchanged as requested. Its real vision-recording.json and captured frames are absent from this main checkout, so run 43652198623 was not replayed through the changed observer. Its existing capture and judge jobs were read as completed/success; that is historical context, not validation of this patch. No real-engine run, live model or spend. A same-sized background region can still resemble the player; this is a calibrated size/presence check, not independent identity recognition. Broader #330 calibration/propose/prove work remains outside this slice.

## Files

- `contracts/observations.schema.json`
- `contracts/examples/observations-missing-player.json`
- `docs/new-work/2026-11-15-missing-player.md`
- `expectrail/anchored.py`
- `expectrail/evaluator.py`
- `tests/test_anchored_observer.py`
- `tests/test_outside_vision.py`

## Architect's change on integration

- An empty answer on one frame would have rejected a good change: a model's single miss (the player
  half behind scenery, say) is not a hidden player, which is missing in every frame (74 of 74 in run
  43652198623). `expectrail/evaluator.py` now counts "not drawn" as a failure only in a run of at
  least `NOT_DRAWN_MIN_RUN` (3) consecutive observed frames; fewer stay missing, so needs-review, as
  on main. It never makes an accept easier.
- Tests: `NotDrawnRunTest` (one, two in a row, or two apart: needs-review; three in a row: fail, with
  the not-drawn reason). Two of the builder's assertions that one frame fails now say needs-review
  for one frame and fail for three; the contract example has three not-drawn frames.
