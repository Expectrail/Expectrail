# Engine readings at the first visual failure

## What changed

For #819, the frame captions identify each observer and show its recorded value on each side. When the visual verdict failed and the export contains no visual timeline, the inspector explains the gap and draws the available engine overlays. Opening the finding by button or keyboard preserves the frame and verdict.

## What was run

All 57 focused viewer tests passed. The keyboard harness covers zero, a missing reading on one side, and a visual gap alongside an engine measurement.

Playwright Chromium opened standalone exports regenerated from the original public stuck-fade and restored records. Both stuck-fade captions showed about −27.565 px at frame 0, and the visual finding still reported the player missing in 83 of 120 frames. The restored captions showed about 2.352 px Before and 0.754 px After at frame 20. Both frame images in each export decoded. No fresh captures were generated.

The historical baseline was fetched. Full Linux discovery passed with 6,120 tests and 57 skips after correcting the work-log headings. The export scan checked 1,402 files with zero errors or warnings.

## Files

- `expectrail/viewer.py`
- `tests/viewer_keyboard.cjs`
- `docs/new-work/2026-11-26-visual-failure-engine-readings.md`
