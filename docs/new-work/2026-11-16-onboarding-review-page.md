# Offline human review page and content-bound answers import (#331)

## What changed

`expectrail onboard --project PATH` now builds object rows (sprite, three engine-box
frames, optional exact recorded observer boxes/scores), plain-language check rows and
first counterexample frames for supplied broken captures. The browser only downloads
answers on a person's explicit action; it has no filesystem write capability, server
or outside requests. Name and every yes/no are required. Missing evidence disables yes.
The explicit human import validates the saved record/input/spec hashes before using
the same shared approval writer as the existing spec writer. Only invented throwaway
specs are approved by tests. No committed spec or real approval was changed.

Three versioned contracts, examples, both readers/writers and wheel inclusion changed
together. Machine review-ready time and human time are separate, with skipped tuning
and proof named. No tuned/proven duration is invented. The #331 baseline/evidence table,
remaining cases and reproduction instructions are in `docs/onboarding-review.md`.
Read-only Breakout and Dodge examples use pinned public trial inputs and local engine
captures. They contain engine diagnostics, not vision evidence; no model ran.

Guard: test change intended (#331). The binding-only tests now parse the hashed review
record, the two CSP-controlled scripts and reused inline image references instead of
expecting a config-download link with no scripts. They still check every binding,
image containment, unchanged game bytes, route tamper refusal and no overwrite.
A valid existing active config can now be reviewed; an explicitly invalid draft flag
still refuses. The unresolved-binding chooser is preserved.

## What was run

`python3 -m unittest discover -s tests -t .`: 4,574 tests passed, 41 skipped, 1088.960 seconds, with no
EXPECTRAIL_* variable set in the shell. Final focused preflight: 116 passed; missing
numpy/PIL discovery: 4,611 tests, zero load errors, 61 selected tests passed. The
offline browser check, both real-engine recorded-stand-in project smokes, two
regression guard-removal red runs and final export scans passed. Patch application
on the exact base was verified byte for byte. Complete changed docs stay below
262,144 bytes (PR #572); the handover has the per-file budget report. No live model, real approval, GitHub write,
workflow dispatch or held-out content was used.

## Not done

Observer calibration/proof orchestration is still missing; the page records those
stages as skipped. No human trial duration, outside visual acceptance or newly
accepted game change is claimed. #331 stays open. Managed Chromium blocks file
navigation in this build environment; browser automation renders the identical HTML
bytes in an offline in-memory document.

## Files

- `expectrail/onboard.py`, `onboard_review.py`, `onboard_page.py`: CLI, measured review,
  strict human answers reader and self-contained page.
- `expectrail/approval.py`, `spec_writer.py`: one signing/linting implementation and a
  final expected-content check; existing readers and thresholds are unchanged.
- `expectrail/viewer.py`: shared frame/overlay helper with optional inline raster reuse.
- `expectrail/contracts.py`, `contracts/onboard-*.v1.schema.json`, examples: contracts.
- `setup.py`, `.gitignore`: ship the new offline modules and track the example generator.
- `tests/test_onboard_review.py`, `test_onboard.py`, `check_onboard_games.py`,
  `onboard_review_browser.py`: synthetic import, security, binding and browser checks.
- `tools/onboard_examples.py`, `docs/onboarding-review.md`, `docs/onboarding-examples/`:
  reproducible public trial examples, guide and issue audit.
