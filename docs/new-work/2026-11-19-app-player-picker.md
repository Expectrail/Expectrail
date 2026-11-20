# Choose a player in the app's folder preview (#370, #652)

## What changed

For a game with several possible players and a missing project config, Check folders
now lets a developer choose a node independently on Before and After. The selection
shows authored sprite and image paths, known image dimensions, atlas regions and
binding issues for that node. The page drops old evidence when a selection or folder
changes. The existing authenticated inspect request still fails closed on a missing
config and offers the picker as structured detail. The picker writes no project files.

## What was run

- The historical fetch for `c169a5e0da304773587304ed47bc8aabcec80da7` succeeded.
  Two new HTTP tests initially failed because the inspect response lacked player data.
- `python3 -m unittest tests.test_app_setup_picker tests.test_app_projects.ConfiguredAppTest tests.test_app_screens`
  passed all 11 tests in 15.402 seconds. Chromium exercised changes to both paths while
  Check folders was pending and an older selection arriving after a newer one.
- `python3 -m unittest discover -s tests -t .` ran 5,421 tests in 503.377 seconds and
  passed with 76 skipped.
- `python3 -m agents.export_scan bench docs README.md apps --paths error` checked
  1,236 public files with zero errors and zero warnings.
- Chromium opened the normal app page against two clean copies of public Breakout at
  `0ac7aed444ea593a023d9b666c211d7ab8acd51e`. On both Before and After, Paddle showed
  its 94 × 18 strip with 47 × 18 regions at (0, 0) and (47, 0). Ball showed its own
  whole 4 × 4 image. Verify refused the missing config. Both 105-file copies kept their
  file hashes. Zero jobs, input probes and renderer probes.

## Not done

Saving a binding from the app and completing verification of a newly configured
Breakout project remain open. This rehearsal used browser automation. Human setup
time and an unassisted first-time user's choices have not been measured.

## Files

- `expectrail/app.py`
- `expectrail/app_page.py`
- `tests/test_app_setup_picker.py`
- `docs/app.md`
- `docs/new-work/2026-11-19-app-player-picker.md`
