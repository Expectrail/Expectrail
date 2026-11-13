# The doctor reader accepts a display check that does not apply (#377)

## What changed

A skipped check with `required: false` and `fix: null` means it does not apply on this system.
The display writer now says this explicitly outside Linux, and the reader accepts that combination.
It stays `skipped`, never `ok`. No new status or change to the readiness calculation was needed.

The schema documents that meaning and requires a non-empty fix for missing checks, even optional
ones, and for required skipped checks. An applicable optional skipped check can still name a fix.
The example shows the non-Linux display and a missing engine: its required OpenGL check is skipped
with a fix, so the example remains not ready. A failed drawing probe still reports `missing` and
is refused if its fix is removed.

Only `display` and `problems` changed in `expectrail/doctor.py`. The vision-check code was not
changed. Eight tests were added in a separate class; every existing test class and function is
unchanged, checked by comparing their syntax trees with main.

## What was run

- `python3 --version`: Python 3.12.14.
- `git fetch --no-tags --depth=1 origin c169a5e0da304773587304ed47bc8aabcec80da7`: succeeded.
- The issue's reproduction on main `6308471ad521dc0ea4490bcf74f5969823329696`: display was skipped,
  optional, with no fix; the reader returned the fix-rule error. After the change, the same command
  returned `[]`. Both complete outputs are in the handover.
- Before the fix, `python3 -m unittest tests.test_doctor.DisplayApplicabilityTest -v`: 8 tests,
  14 assertion failures including subtests. The failures were read before changing the writer,
  reader, schema or example. After: the same command, 8 tests, OK.
- `python3 -m unittest tests.test_doctor -v`: 34 tests, OK, 1 existing real-engine test skipped.
  These include darwin and win32 platform selection with the existing stand-in machine, Linux
  with and without xvfb-run, required skipped checks blocking readiness, and both the reader and
  JSON Schema validator checking the fix rule and example.
- A `python3 -S` reader check: both selected platforms and the example returned no problems,
  without third-party imports. Tool discovery was a stand-in. The first supplementary attempt
  patched win32 without that stand-in and stopped in Python's `shutil.which`: this Linux interpreter
  has no Windows `_winapi`. Both attempts are logged; this was not a native Windows run.
- Before: `python3 -m unittest discover -s tests -t .`: 2788 tests, 7 failures, 8 errors, 25 skipped.
  The exact 15 failure/error entries match the accepted environment baseline.
- First after-change full suite: 2794 tests, 7 failures, 9 errors, 25 skipped. It added
  `tests.test_ground_under.SlopeTest.setUpClass`: a headless Godot import died with SIGABRT.
  That log is retained. An isolated rerun with import stdout/stderr captured passed both slope
  tests; the import returned 0. The original crash's cause is not established.
- `python3 -m unittest tests.test_doctor tests.test_ground_under.SlopeTest -v`: 36 tests, OK,
  1 existing skip. This also ran the slope tests immediately after the doctor tests.
- Final full-suite repeat, without further code changes: 2796 tests, 7 failures, 8 errors,
  25 skipped. Both result summaries were read. Comparing names and multiplicities gives exactly
  the same 15 failure/error entries as before, with no added or removed entry. The first after-run
  and its unexplained import crash remain in the handover for the architect to review.
- `python3 ../Expectrail-377-handover/check-working-tree.py`: the merge guard's check function
  examined all 5 files; 0 reasons. This is not the commit-based CLI. `git diff --check`: clean.

- **Validated by the architect session** (its own runs, separate from the builder's above), on
  Ubuntu with Python 3.13.18, main at `ada0dd3`, with Godot 4.7.2 present: the reproduction gave the
  fix-rule error before the patch and `[]` after; the patch applied with `git apply --check` and no
  adjustment; `tests.test_doctor.DisplayApplicabilityTest`: 8 OK; `tests.test_doctor`: 34 OK (1
  existing skip); the full suite on unchanged main ran 2902 tests, OK (27 skipped), and with the
  change 2910 tests, OK (27 skipped), with no failures or errors on either side. The builder's one
  `SlopeTest` import crash (SIGABRT) did not happen in either of these two full runs, which include
  `tests.test_ground_under.SlopeTest` with the real engine; its cause is still not established.

## Not done

Native macOS and Windows, CI and the commit-based merge guard command were not run. The new doctor
tests use a stand-in engine. The full suite and slope diagnostic did run the cached Linux Godot;
they do not prove that a native macOS or Windows display works.
The local full suite has
the accepted environment failures; it is not a green run. The other macOS failures in #378 and
the vision check in #379 are outside this change.

## Files

- `expectrail/doctor.py`
- `contracts/doctor.v1.schema.json`
- `contracts/examples/doctor.json`
- `tests/test_doctor.py`
- `docs/new-work/2026-11-13-doctor-macos-display.md` (new)
