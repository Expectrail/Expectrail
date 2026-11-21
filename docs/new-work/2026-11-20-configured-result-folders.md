# Show the selected folders when reopening a configured run (#705)

## What changed

The local app records the resolved Before and After folders it used to prepare a configured comparison. The result and Past runs display that pair even after either folder is renamed or the app restarts. For an older configured run, the app labels the recorded checkout and explains that the original selection is unavailable.

The two paths are written together in one private file for the newly created job. The worker still verifies the snapshots. If the display record is unavailable, verification can proceed and the result identifies the checkouts. A reader refuses linked, oversized or malformed display records. The export continues to use the worker request and its evidence.

## What was run

- `python3 -m unittest tests.test_app_selected_folders -v` passed four tests. The original result returned the snapshot paths and failed the new regression. The tests cover the stored request, export HTML, reopened history, damaged or absent local metadata, a repeated job ID and a failed metadata write.
- `python3 -m unittest tests.test_app_selected_folders tests.test_app tests.test_app_projects tests.test_app_project_picker tests.test_app_screens` passed all 54 tests in 43.800 seconds.
- `python3 -m tests.test_app_selected_folders` exercised the real loopback app in Chromium 156.0.8078.79 with an offline fixture worker. The browser submitted a configured comparison, displayed both selected folders, reopened the result after a form edit and reopened it again after a server restart. It also opened an earlier configured job and showed its recorded checkouts. There were zero page errors.

A separate Chromium rehearsal drove the real worker on two prepared copies of the public kinematic-character game at `b761b4c`. The app showed **Before gravity repair** and **After gravity repair** at submission, after editing the form, and after restarting. The worker used the `base` and `head` snapshots and ran both Godot 4.7.2 replays. The engine passed the check. The recorded visual answers did not match local rendering, so the result was **needs-review**. Neither selected path occurred in the 75,316-byte exported evidence page. The source tree digests matched after the rehearsal.

## Not done

The browser rehearsal used prepared local projects. Unaided developer time and native desktop testing remain unmeasured.

## Files

- [App job creation and status](../../expectrail/app.py)
- [Selected-folder tests and Chromium rehearsal](../../tests/test_app_selected_folders.py)
