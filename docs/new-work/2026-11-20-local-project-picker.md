# Choose a local Godot project and find its Before copy (#710)

## What changed

The app can open a desktop folder dialog, remember six projects across restarts, and return setup
problems for each selected version. It suggests a sibling or a registered worktree and can
materialize the previous local commit on request. Folder selection uses the existing authenticated
loopback API.

## What was run

Five HTTP tests in `tests.test_app_project_picker` passed. They cover authentication, refusing
path injection, a sibling symlink, a false Git checkout pointer, recent projects, per-field
messages and starting a job with a copy of the previous commit. The Git test uses a real
temporary repository and a linked worktree.

In a manual Linux smoke check under Xvfb, the desktop dialog returned the selected folder with a space in its name.
Cancel returned no folder.

Full discovery (`python3 -m unittest discover -s tests -t .`) ran 5,762 tests in 1,539 seconds and passed with 56 skipped. The export scan reported zero errors and zero warnings.

## Not done

The page controls, drag and drop, shared styling and quickstart follow in the next change.

## Files

`expectrail/app.py`, `tests/test_app_project_picker.py`, `docs/app.md` and this entry.
