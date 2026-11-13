# The evidence viewer as one file that opens offline (#264)

## What changed
- Every viewer folder now also has `evidence.html`: the same page in a single file, with every frame
  embedded as a `data:` URI. You can keep it, attach it or send it, and it opens with no folder and no
  network. `expectrail.viewer.export` writes it, and `viewer.write` calls it, so the gate's viewer and
  the job viewer from `expectrail report` both get it. `expectrail report JOB` prints its path
  ("one file to keep or send").
- Only the folder's own frames are embedded. A frame must match the frame-name pattern, be a regular
  file (not a link), start with the PNG signature and still have the sha256 its view recorded.
  A frame that fails any of these tests, or that would push the embedded frames past 32 MB, is left
  out. The file then says how many frames were left out and why.
- The export's decision, state, reasons, record, job and reproduction command are the folder page's,
  unchanged. It carries the same evidence and never says more.
- `index.html` links to `evidence.html` ("Download this evidence as one file"). The single file has
  no link and no `src` or `href` at all, and keeps the page's Content-Security-Policy.

## What was run
- `python3 -m unittest tests.test_viewer`: 24 tests, OK. Five are new:
  - the export has every frame byte for byte, with the same decision and payload;
  - it refers to nothing outside itself;
  - a changed, missing or linked frame, or a path outside the folder, is left out and counted;
  - the size cap leaves frames out and says so;
  - an empty result exports as not success.
  The job-viewer test now also checks the printed path and the export's decision.
- Full suite on this branch (main at 8a3e83f): see the pull request.
- Looked at in Chromium (Playwright) from `file://`, at 1280x900 and 390x844. I used a failing
  stand-in gate run whose placeholder frames I replaced with real 320x180 PNGs; the stand-in's own
  frames are 33-byte placeholders that no browser decodes. What I saw:
  - both frames decoded from the embedded data;
  - the right arrow stepped from frame 30 to 31 on both sides;
  - the "Offline copy: 52 frames embedded" line showed;
  - no console errors, no requests other than `file:` and `data:`, no horizontal scroll at either
    width.

## Not done
- The other #264 slices: the viewer for a real failing and a real passing Godot run under `docs/`
  (needs the engine), the visual observer's timeline, the model-explanation link, and the
  two-minute trial with one person (Sean's).
- The format is one HTML file, not a zip. It opens offline in any browser with nothing to unpack.

## Files
- `expectrail/viewer.py`, `expectrail/orchestrator/cli.py`
- `tests/test_viewer.py`
- `docs/new-work/2026-11-13-viewer-offline-export.md` (this file)
