# Save a selected player's draft setup from the local app (#370, #652)

## What changed

A developer can select a player and see the destination, setup filename, route directory,
remaining choices and whether saving requires running their project. The explicit
confirmation authorizes the same proposal and no-overwrite publication used by init.
The app binds a single-use review to the side, folder, selected player and project bytes.
When it needs headless measurements it runs a disposable copy of the reviewed bytes
and rechecks the destination before publishing. Requiring isolated replay blocks a
setup that needs this probe. Missing gameplay controls produce the planner's guidance.

## What was run

- The five initial authenticated HTTP cases failed against the previous app, which
  lacked the save endpoint and review. They passed after implementation.
- `python3 -m unittest tests.test_app_save_setup tests.test_app_setup_picker tests.test_app_projects`
  passed all 26 tests in 13.224 seconds. The tests cover both draft filenames, dismissal
  and confirmation in Chromium, changed project bytes during a probe, wrong-side or reused
  review IDs, sandbox refusal and a missing gameplay control.
- The required historical fixture fetch succeeded. An initial discovery run with six
  restricted entries held aside was stopped when file-presence checks failed. Its public
  export scan counted 1,234 files with zero errors or warnings. The six entries were
  restored unchanged.
- On the complete public worktree, `python3 -m unittest discover -s tests -t .` ran
  5,435 tests in 536.692 seconds, with 76 skipped and zero failures or errors.
  `python -m agents.export_scan bench docs README.md apps --paths error` checked
  1,239 files with zero errors or warnings. Opt-in Godot/Bubblewrap repair tests
  were not run here.
- In Chromium with Linux Godot 4.7.2 and separate clean public Breakout copies from
  `0ac7aed444ea593a023d9b666c211d7ab8acd51e`, selecting Paddle and Ball and
  dismissing the save preserved all 105 source files per copy. Confirming Ball
  reported no movement/pointer control and asked for a route. Its copy stayed
  byte-for-byte unchanged. Confirming Paddle wrote exactly two files on its side,
  `expectrail.project.draft.json` and `routes/draft-first-0a650cac4349dcfb.json`
  with 303 events. The saved review named the 94 × 18 player image and two 47 × 18
  regions, and left the representative texture open for a person. Check folders
  read the saved draft. Job history stayed empty.

## Not done

The pointer route still needs a gameplay replay and a human decision about the
representative image. This automated browser session did not run verification, call
a model, approve checks or measure first use by a developer.

## Files

- `expectrail/app.py`
- `expectrail/app_page.py`
- `tests/test_app_save_setup.py`
- `docs/app.md`
- `docs/new-work/2026-11-19-browser-draft-save.md`
