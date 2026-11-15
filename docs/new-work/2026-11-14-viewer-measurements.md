# Show the first measured difference and the first failure (#264)

## What changed

The viewer compares recorded engine values for the same check at the same tick. It opens findings at the first paired difference when one is measured. The finding keeps its own frame and verdict. Keyboard shortcuts move between the two. A missing image stays missing.

Both viewer formats show measurement tables, bounds, gaps and the opening pictures without JavaScript. Both public samples were rendered again from their existing embedded evidence.

## What was run

The viewer unit tests, the keyboard test using the viewer script, and both full suite logs are in the handover. The public reject sample first differs at frame 0 and first fails at frame 5. The passing sample has no paired engine measurements and no captured pictures. Rendering retained the existing payload of each sample.

The two exports were opened from disk in Chromium at 1280 × 900 and 390 × 844 with JavaScript off and reduced motion on. Both tables opened. With scripts on, Right stepped to frame 1, F returned to frame 5 and D returned to frame 0. The browser log and four screenshots are in the handover.

## Not done

The two-minute trial with an unfamiliar reader still needs a person. No new replay, model explanation or live model call was used to produce these examples.

## Files

- `expectrail/viewer.py`
- `docs/viewer.md`
- `docs/viewer-samples/clean.html`, `docs/viewer-samples/fall-through-bug.html`
- `tests/test_viewer_measurements.py`, `tests/viewer_keyboard.cjs`
- `docs/new-work/2026-11-14-viewer-measurements.md`
