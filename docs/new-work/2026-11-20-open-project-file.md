# Open a local project.godot file in the app (#704)

## What changed

Before and After can each take the full path to a project folder or its regular
`project.godot` file. The configured app uses the containing folder for inspection,
reviewed draft saves and verification requests. It checks the supplied file before
resolving its path so a symbolic link cannot stand in for a descriptor. An invalid
file input reports that verification did not start. Manual checkout inputs still take
folder paths.

## What was run

- Before the fix, the new HTTP regression tests reproduced a configured project's
  `NotADirectoryError`, a missing setup preview and a symbolic link named
  `project.godot` opening a different project folder. A separate failing assertion
  reproduced the missing `jobStarted: false` on invalid input.
- `python3 -m unittest -v tests.test_app_project_file tests.test_app_projects tests.test_app_save_setup tests.test_app_setup_picker tests.test_app`
  passed all 59 tests. The new tests cover file-based inspection and draft saving,
  changed project bytes, a substituted descriptor link, invalid inputs on either side,
  manual checkout behavior and the two source snapshots in a stored verification
  request judged under Before's route selection. [Regression tests](../../tests/test_app_project_file.py)
- Chromium opened two temporary copies of public Breakout at
  `0ac7aed444ea593a023d9b666c211d7ab8acd51e` using their descriptor paths.
  It showed Paddle's 47 × 18 atlas regions and Ball's 4 × 4 image. A reviewed Paddle
  save with the local headless engine wrote `expectrail.project.draft.json` and
  `routes/draft-first-0a650cac4349dcfb.json` in Before. After retained its original
  bytes. The save created zero jobs. The first probe failed when the engine could
  not create its user data directory. The completed run used writable temporary XDG
  data, cache and config directories.
- In the same browser, Verify submitted a configured fixture pair with different
  route selections. One job ran with the fixture worker and reported needs-review.
  An independent Chromium run submitted the pinned public kinematic-character copies
  to the real worker by descriptor. It reached the same preflight needs-review as
  folder input. [Independent run](https://github.com/Expectrail/Expectrail/issues/704#issuecomment-7043120162)

## Not done

Full suite, paid models and a first-time human trial were not run by the builder.

## Files

- `expectrail/app.py`
- `expectrail/app_page.py`
- `docs/app.md`
- `tests/test_app_project_file.py`
- `docs/new-work/2026-11-20-open-project-file.md`
