# Check folders reads a saved menu route without starting Godot (#370)

## What changed

A developer who opens a Godot project with an unfinished setup can now review its saved menu route even when the engine is unavailable. Check folders checks the route against its content-addressed filename, the saved draft and the current project's input map and viewport. A pause-only route gets a specific next step. A saved route still needs a replay to demonstrate gameplay.

## What was run

- On main `f8c0879`, the new local-app HTTP test hit the engine probe on all five menu-route cases. With the change, `python -m unittest tests.test_app_projects.ConfiguredAppTest` passed all six tests. The new test covers pointer and action-only drafts, an out-of-viewport position, an unknown action and an event beyond the end.
- In Chromium, two copies of public Breakout at `0ac7aed444ea593a023d9b666c211d7ab8acd51e` had pending drafts. Before contained the older six-event pause route. After contained the [303-event pointer route](../outside-trials/breakout-pointer/init-generated/route.json). With a counting stub in place of the game probe, Check folders showed both saved drafts and named Paddle and Ball. Before said “The saved route only uses pause. Choose inputs that start and exercise gameplay.” After asked for a replay. Verify displayed “Verification did not start.” The app created zero jobs, the game probe received zero calls and every source file had the same digest after the rehearsal.
- `python3 -m unittest discover -s tests -t .` ran 5,407 tests in 505.980 seconds with 76 skipped and no failures or errors. The opt-in Godot and Bubblewrap repair tests were not run here.
- `python -m agents.export_scan bench docs README.md apps --paths error` scanned 1,234 files with zero errors and zero warnings.

## Not done

This automated rehearsal measured folder inspection. An unaided developer session, gameplay replay and a two-observer verdict were not run here. The in-app picker and save flow remains under #652. Older action-only drafts in the separate offline binding review are tracked in #671.

## Files

- `expectrail/app.py`
- `tests/test_app_projects.py`
- `docs/app.md`
- `docs/new-work/2026-11-19-static-route-review.md`
