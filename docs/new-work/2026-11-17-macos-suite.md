# The full suite on a macOS runner, reported and never gating (#378)

## What changed
`.github/workflows/macos.yml` runs the whole suite on GitHub's `macos-14` image and writes the count,
the result line and every failing or erroring test to the job's summary, so what the suite assumes about
Linux is measured on a Mac instead of guessed from one log. The suite step has `continue-on-error`, so a
failure on macOS never turns a pull request or main red. It holds `contents: read`, no secret, no
environment and no model; it installs no Godot, Chromium or bubblewrap, so the tests that need them skip
as they do on a Mac without them. It runs on a change to itself or its summary tool, on main, daily and
by hand.

The summary is `tools/macos_suite_summary.py`. It says only what the log shows: a log with no final
`OK` or `FAILED` line (empty, cut off by the time limit, or missing) is reported as a suite that did not
finish, never as a pass.

The schedule's day field is written `0-6`: the merge guard's line check reads a star before a closing
quote (`'17 9 * * *'`) as a YAML alias. That false positive in `tools/merge_guard.py` is filed on its
own; this change does not touch the guard.

Making the job a required check is Sean's decision once its counts are clean.

## What was run
- `python3 -m unittest tests.test_macos_suite`: 11 tests, OK (the summary's cases, and the workflow's
  permissions, report-only shape, time limit, and that the guard reads no alias in it).
- The full suite on the branch merged with main at aefed02, with this change: 4,815 tests, OK, 55 skipped.
- `python3 -m tools.merge_guard --base origin/main --head HEAD`: nothing to report in 5 files.
- The macOS job itself: recorded in the pull request once GitHub has run it.

## Not done
- Fixing what the macOS run finds. That is the next slice of #378, from the job's own list.

## Files
- `.github/workflows/macos.yml`
- `tools/macos_suite_summary.py` (and its `.gitignore` exception)
- `tests/test_macos_suite.py`
- `docs/new-work/2026-11-17-macos-suite.md`
