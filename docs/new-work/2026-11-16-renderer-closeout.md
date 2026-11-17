# Audit recorded renderer evidence and name local incompatibility (#515)

## What changed

Read #515 and all comments, and #516, #525, #528 and #532 with their comments.
The [audit](../recorded-renderer-closeout.md) maps each Done when case to tests,
source and measurements on main. Exact image/question matching is retained.
No recording answer or provenance was invented or changed.

Added a typed readiness result so malformed/missing evidence is kept separate
from a different or unknown recording environment. Local capture compatibility
now reports a named skip for mismatch/unknown, with the files and environments;
required capture checks still fail. Corrupt files and an empty collection fail
in both modes. Doctor and verdict behaviour are unchanged.

Added offline regression tests for those distinctions and an app HTTP/worker/
report test using the actual frame-111 images with a stand-in replay. Corrected
the pixel description to include both changed channels at the second pixel.

## What was run

- Historic-base fetch and branch/main fetch. Base:
  `d877ddb647161e4af28aa554e7886d91e1b83f5b`.
- Before full suite: 4,539 tests, OK, 58 skips, no failures/errors, 412.640s.
- Before code change: the new six-test module produced three failures (two
  subcases in the renderer/version test and one unknown-provenance case).
- Focused closeout, renderer and configured-app tests: 59 tests, OK, one named
  missing-Godot skip, 9.771s.
- Reran the pixel measurement tool offline: exactly reproduces the committed
  measurements, including the overlap between drift and a subtle recolour.
- Real Godot plus the existing local virtual display reproduced the old failure.
  Final local probe: one named skip; required mode: one expected failure.
- Final full suite (verbose): 4,545 tests, OK, 58 skips, no failures/errors,
  421.541s. Compared failure/error names: empty before and after.
- The first complete after attempt had one historic-worktree setup error while
  disk was full; the second stalled in HTTP-server cleanup and was interrupted.
  Both logs are retained. The targeted worktree test and final full run passed
  after space recovery, without further code/test changes.
- All 47 renderer/closeout tests load without NumPy and Pillow. Export scan:
  763 files, zero errors/warnings. Relative documentation file links resolve.

## Not done

No live model, spend, dispatch, GitHub write, push, approval or game-source edit.
No new game replay on both renderer builds, and no dual-renderer accept claim.
The recorded pixel fixtures and original capture metadata supply the comparison;
the app test repeats one trace row/image and is explicitly a stand-in.
The four Run it recordings still lack provenance. Only Sean can recover it or
commission recordings; the strict capture rollout remains blocked. No workflow,
capability-ledger or release-dossier file changed. Part of #515.

## Files

- `expectrail/renderer.py`: typed readiness status; existing diagnostic reader retained.
- `tests/test_recorded_renderer_drift.py`: named local skip, strict required check retained.
- `tests/test_renderer_closeout.py`: local/required outcomes and the app result/report.
- `docs/recorded-renderer.md`: precise pixel description and audit link.
- `docs/recorded-renderer-upgrades.md`: local/required result semantics.
- `docs/recorded-renderer-closeout.md`: case-by-case evidence and remaining human steps.
- This work log. Logs and exact handover commands are in the ZIP.
