# Choose Before and After folders in the local app (#710, #370)

## What changed

Each project field now has a button that opens the existing desktop folder dialog.
Choosing a folder updates just that field and clears its prior inspection. Cancelling
preserves the current selection. If the dialog fails, the field shows the reason and
explains how to enter the path manually. A developer can also paste a descriptor path.
Verification still starts from the Verify button.

## What was run

- `python3 -m unittest tests.test_app_desktop_chooser tests.test_app_project_picker tests.test_app_project_file tests.test_app_setup_picker tests.test_app_screens tests.test_package` passed
  with 52 tests and one skip. Both new tests ran. The Chromium regression covered choosing
  both folders, cancelling, preserving a manual edit while the dialog was open, and invalidating
  a previous inspection. Six chooser requests started zero jobs.
- A separate Linux rehearsal used Chromium at 390 px, a private virtual display, and the real
  Python Tk dialog. The Before and After buttons selected two copies of the public
  [Breakout project](https://github.com/mike0697/Breakout/tree/0ac7aed444ea593a023d9b666c211d7ab8acd51e)
  by clicking directory entries. Cancel kept the After path. Check folders then offered
  Ball and Paddle on both sides. There were zero page errors, external requests,
  verification jobs or horizontal overflow.
- `python3 -m tools.front_door` checked the quickstart links and ledger references with zero problems.

## Not done

The native dialog rehearsal was automated. Unaided developer timing, macOS and Windows
dialog behavior, and a gameplay verdict from this selection flow were not run.
Recent projects, Before suggestions, folder drop and the wider first-screen visual pass remain open.

## Files

`expectrail/app_page.py`, `tests/test_app_desktop_chooser.py`, `docs/app.md`,
`docs/quickstart.html` and `docs/first-user-test.md`.
