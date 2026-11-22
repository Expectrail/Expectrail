# Open setup review from the recent-folder feedback (#710)

## What changed

A developer who selects a recent Godot project without an Expectrail config now sees **Check folders** as the first next step. The button opens the setup review for the selected project. The field message also names the terminal command as an alternative. Projects with a pending setup still show the instructions for that draft.

## What was run

- Before the change, the recent Before and After fields both directed the developer to `expectrail init`. The regression test failed because the error did not name **Check folders**. After the change, all six tests in `python3 -m unittest tests.test_pending_project_setup` passed. The controls include an invalid config, a pending draft, and folders with a missing or linked Godot descriptor.
- In Chromium 156 at 390 pixels, I used a disposable copy of `tests/projects/crate-run/project` without its config. I selected it through the local app's folder chooser, reloaded the page, and selected it from both recent-folder lists. The chooser's return value was supplied by the test. Each field showed the local action. Clicking **Check folders** opened setup inspection for `main.tscn` on both sides. Every project file retained its digest. The app created zero jobs, and the browser recorded zero external requests and zero page errors.

- On a fresh copy with no config, the command entry point (`expectrail.cli:main`) returned 5 for `verify --project` with both setup options in the error. It did not create the requested job store.
- Full discovery ran 5,990 tests in 493.106 seconds and passed with 81 skipped. The shared filesystem had exhausted its file entries during earlier runs. The successful run used memory-backed temporary storage and had space for tests with fixed paths in `/tmp`.

## Still open

The two-version layout warning has a separate reproduction. An unaided developer session on their own game and native macOS or Windows use were not run here. [Layout rehearsal](https://github.com/Expectrail/Expectrail/issues/710#issuecomment-7082207345)

## Files

- `expectrail/project_job.py`
- `tests/test_pending_project_setup.py`
- `docs/new-work/2026-11-22-missing-setup-guidance.md`
