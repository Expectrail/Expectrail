# A folder reached through a link is still that folder: the macOS temporary-folder failures (#378)

## What changed
On macOS every temporary folder is reached through a link: `tempfile` gives `/var/folders/...`, and
`/var` is a link to `/private/var`. Code that resolves one side of a comparison and not the other
reads its own project as outside itself. Sean's macOS log on #378 had a group of these. The same
layout made on Linux (`TMPDIR` set to a link to a real folder) reproduces 14 failures on unchanged
main at ec0919b, all of which pass with an ordinary `TMPDIR`. Three were in the product:

- `expectrail/onboarding.py`: `resource()` compared a resolved file with an unresolved project
  folder, so `expectrail init` and `inspect` refused every file of a project reached through a link
  ("Restore res://main.tscn inside the project"). `entry_scene()` had the same mistake for a
  `uid://` main scene. Both now resolve the project folder first. A link out of the project, `..`,
  and a missing file are still refused.
- `expectrail/onboard.py`: `local_file()` had the same mistake and the same fix.
- `tools/ci_bundle.py`: the two-job gate's judge keyed its saved runs by the base checkout as given,
  while the gate looks the base up by its resolved path. Behind a link, a correct fix read as
  "the base commit has no Godot project" (needs-review) instead of accept, and a regression as
  needs-review instead of reject. That failed closed, never open. The judge now resolves the base
  and its own temporary folder.

The other eleven were tests that compared the path they made with the resolved path the code
reports (`test_app`, `test_live_repair_kit`, `test_package` (4), `test_repair_command`,
`test_trial_stops` (3)), and one stand-in replay in `test_unknown_actions` that told the base from
the head by `is_relative_to` on two spellings. That stand-in mistake made a test expecting
needs-review see accept: the stand-in, not the gate, put the head's answer on the base. These tests
now use the resolved temporary folder, or compare resolved paths.

So this cannot drift back: `tests/test_linked_paths.py` builds the link itself and holds the three
product cases (5 of its 6 tests fail without the fixes; the sixth holds that the refusals still
refuse), and CI's `test` job now runs the whole suite with `TMPDIR` behind a link.

The macOS runner job is a separate pull request (#574). Its only run so far (43931782507) was
cancelled before a runner was assigned, so nothing here comes from a Mac.

## What was run
- Full suite on main at ec0919b with `TMPDIR` behind a link: 4,526 tests, 13 failures and 1 error,
  52 skipped. The same 14 tests with an ordinary `TMPDIR`: OK.
- The same 14 with the fixes, `TMPDIR` behind a link: OK.
- `tests.test_linked_paths`: 6 tests, OK. With the three product files put back as on main: 2
  failures and 3 errors; the refusal test passes either way.
- The full suite on this branch (main at 55e4636), `TMPDIR` behind a link: 4,835 tests, OK, 55 skipped.
- Not run on macOS: no Mac and no macOS runner was available.

## Not done
- The rest of #378 can only be measured on a Mac: run the suite there, or turn on macOS runners
  for the repository (Sean). The other groups in the November 13 log (`timeout`, `sha512sum`,
  `os.unshare`, `xvfb-run`, `__CF_USER_TEXT_ENCODING`) are skipped or handled on main since #415
  and #406, by reading the code; that has not been run on a Mac.
- The path-length and case-insensitive glob failures were not reproduced here.

## Files
- `expectrail/onboarding.py`, `expectrail/onboard.py`, `tools/ci_bundle.py`
- `tests/test_linked_paths.py` (new)
- `tests/test_app.py`, `tests/test_live_repair_kit.py`, `tests/test_package.py`,
  `tests/test_repair_command.py`, `tests/test_trial_stops.py`, `tests/test_unknown_actions.py`
- `.github/workflows/ci.yml` (the `test` job's temporary folder)
- `docs/new-work/2026-11-17-linked-temp-folders.md`
