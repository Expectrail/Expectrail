# Visual timelines and public sample evidence (#264)

## What changed

The viewer reads each public check's saved visual observations and verdict. Their
digests must match the findings row and the spec. Missing, changed, linked or
inconsistent evidence is omitted with a note. Engine and visual timelines stay
separate. Gaps mark frames that were not observed; missing objects and frames
with no applicable relation have different marks. The recorded coverage status
is shown without deciding anything again. Visual-only failures select visual
overlays first, and a button switches the measurement source.

The page says when vision did not run, including a job's `PROVIDER_FAILED`, while
keeping a recorded reject. A provider which returned no answer is not described
as never called. Keyboard navigation is tested using the actual script with a
DOM stand-in, including empty views, synchronized frames, gaps, bounds, overlays,
finding selection and the supplied real exports. Empty views no longer crash
the keyboard handler.

Run it passes its sample id to the viewer. Its reproduction command is now
`python3 -m expectrail.runit run --sample NAME --out NAME-run`, not a temporary
checkout path. No verification or vision rule changed.

Sean's supplied Linux runs are published as self-contained pages under
`docs/viewer-samples/`: clean accepts, fall-through-bug rejects. The records,
job facts and embedded frame bytes are preserved. The clean export kept no
images; the rejecting export embeds 24 frames. Neither supplied export contains
raw visual measurements, so their visual panels say those measurements were
not supplied. No visual measurements were guessed. A PNG happened to contain a key-shaped base64
sequence. Escaping its JSON separators preserves its bytes while keeping ordinary
text keys scannable; the export scanner is unchanged. Provenance retains the
source status documents and content digests.

## What was run

- Base: PR #416, `a07b4e12458b239dd2dd0c1054072f7d8511dbb3`, on
  `chatgpt/256-exercised-coverage` as requested.
- `git fetch --no-tags --depth=1 origin c169a5e0da304773587304ed47bc8aabcec80da7`:
  succeeded before the baseline.
- Before: `python3 -m unittest discover -s tests -t .`: 3,095 tests;
  8 failures, 9 errors, 25 skips. Sean authorized the known environment failures.
- Test first: `python3 -m unittest tests.test_viewer_timeline -v`: 9 tests,
  7 failure entries and 3 errors, including subtest failures, before implementation.
- `python3 -m unittest tests.test_viewer_timeline tests.test_viewer tests.test_runit tests.test_two_observers tests.test_export_scan -v`:
  123 tests, OK. No Godot or paid model calls in this focused run.
- `publish_samples.py` from the handover: the supplied folders passed the Run it
  publishing check; 24 embedded PNG hashes verified; both decisions, records,
  jobs and all original frame entries preserved. It renders existing evidence;
  it does not replay or call a model.
- The image-encoding regression failed before the fix (`image-red.log`); the
  final focused run includes the unchanged public export scanner.
- After: `python3 -m unittest discover -s tests -t .`: 3,107 tests; `FAILED (failures=8, errors=9, skipped=25)` (`after.log`).
- `python3 compare_suites.py before.log after.log`: PASS. The same 17 failure/error entries, with identical names, kinds and multiplicities; nothing new failed, no exclusions (`comparison.log`).

## Not done

The two-minute trial with a person who has not seen the run still needs a person.
This slice was not looked at in a browser. The keyboard test uses Node and a DOM
stand-in; it is not a browser rendering test. Real runs were supplied by Sean,
not made on this machine. Their absent visual measurements cannot be restored
from a verdict alone. No model-written explanation was added. CI was not run.
No commits, pushes or GitHub writes were made.

## Files

- `expectrail/viewer.py`
- `expectrail/runit.py` (the viewer call only)
- `tests/test_viewer_timeline.py`
- `tests/viewer_keyboard.cjs`
- `docs/viewer.md`
- `docs/viewer-samples/clean.html`
- `docs/viewer-samples/fall-through-bug.html`
- `docs/viewer-samples/provenance.json`
- `docs/new-work/2026-11-13-viewer-timeline.md`

## Architect run and one wording fix (Linux, on #416 at f4dc9b4)
The viewer said "Vision did not run" for a check vision was not asked about. The gate does not ask vision about a check the engine's record already fails, so on the real fall-through sample, which has recorded vision answers, the page read as if vision had failed. It now says "Vision was not asked about 1 after-change check: the engine's record already fails it, and a failure from either observer rejects". PROVIDER_FAILED keeps "did not run". The samples were regenerated with `publish_samples.py` from the same supplied zip: records and frames unchanged. Full suite: 3202 tests, OK, 31 skipped. Rendered in headless Chromium at 1280 and 390 px wide: no console errors.
