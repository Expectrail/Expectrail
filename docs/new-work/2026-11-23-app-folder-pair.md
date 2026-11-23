# Warn when Before and After select the same copy (#803)

## What changed

Once both fields contain a path, the local app asks its existing paired folder
check to resolve them. If both identify the same project, the page points to
**Choose Before folder** and still allows a deliberate baseline run. A folder
and its `project.godot` file identify the same copy. Separate copies can share
a name and have identical contents.

The same response puts setup and layout problems beside the affected field.
Editing either selection clears the old pair result. A reply for an earlier
selection cannot bring its warning back. The check uses the paths confirmed
by the chooser or entered in the form.

## What was run

On November 23, the Chromium regression on main `d968fdad` failed because
selecting one recent folder twice produced no same-copy warning. A second
regression caught the Before field remaining at “Checking the selected
folder…” when the developer selected After before the first reply.

On Linux, `python3 -m unittest tests.test_app_desktop_chooser tests.test_pending_project_setup`
passed all eight tests. In Chromium 156 the warning covered the recent-folder
and descriptor forms. Choosing a separate same-named copy cleared it, both
before and after editing the copy's scene. A missing scene produced a layout
warning in both selection orders. Clearing a field while a reply was in
flight kept the stale warning off the page. Deliberately verifying one copy
submitted one job using the test replay backend.

At `0ecc5998`, Chromium selected an unconfigured game and its own
`project.godot`. The page offered a baseline, then Verify stopped at
inspection and created zero jobs. The regression failed on that invitation.
With the fix, the same-copy notice still names **Choose Before folder**,
the field points to **Check folders**, and the baseline invitation appears
only when the paired check reports both fields ready. The eight focused
tests passed, including the configured game's baseline submission.

The drop rehearsal checked all three empty chooser requests and the exact
Before and After paths subsequently sent for validation. In a fresh
environment with the repository's test dependencies and without NumPy, Pillow
or Playwright, the markup test passed and the browser test skipped by name.

## Not done

The browser rehearsal used a stand-in for the desktop folder chooser.
An unaided developer session remains open under #370.

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/new-work/2026-11-23-app-folder-pair.md`
