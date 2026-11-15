# The merge guard's diff no longer hangs on very long lines (#472)

## What changed

- `tools/merge_guard.py`: `_lines` used `difflib.ndiff` unless lines(old) x lines(new) reached 4
  million. On #472, `docs/viewer-samples/fall-through-bug.html` (7.7 MB, lines up to 24,190
  characters) made ndiff compare changed lines character by character, and the `merge-guard` check was
  cancelled at its 5-minute limit; the guard reproduced the hang with main's copy. `_cheap` now also
  chooses the plain line diff when the text passes 2 million characters or any line passes 1,000.
  The plain diff yields the lines only one side has, which is what the rules read.
- `tests/test_merge_guard.py`: `test_long_lines_use_the_cheap_diff_and_finish` (60 lines of about
  24,000 characters: finishes in under 5 seconds, finds the added line and the changed rows, and
  `_cheap` chooses the plain diff; a small YAML change still uses ndiff).

## What was run

- `tests.test_merge_guard`: OK. The new test fails on main at its threshold assertion. On this
  synthetic data main's ndiff happened to finish in time, so the hang itself is shown by the guard's
  reproduction on #472, not by this test.
- `python3 -m unittest discover -s tests -t .`: 3,606 tests, OK (42 skipped).

## Files

- `tools/merge_guard.py`
- `tests/test_merge_guard.py`
- `docs/new-work/2026-11-15-merge-guard-long-lines.md`
