# Run both project folder buttons in browser CI (#710)

## What changed

The web-capture job runs the local app’s desktop chooser rehearsal immediately after installing Chromium. Calling the module directly makes a missing browser fail the job. The rehearsal drives the page and loopback server with a stand-in for the native dialog.

## What was run

On Linux, `python -m tests.test_app_desktop_chooser` passed with Chromium 156. It exercised both selections, cancellation, concurrent chooser prevention, a manual edit during a dialog, stale review state and field errors. At 390 pixels wide it recorded six empty-body chooser requests, zero jobs, zero page errors and no horizontal overflow.

With an empty browser cache and Chromium removed from PATH, the same command exited 1 at browser launch. The export scan reported zero errors and zero warnings.

## Not done

The hosted web-capture job will exercise this step on the PR. The separate desktop rehearsal with the real dialog is recorded in the [chooser work log](2026-11-21-desktop-chooser.md).

## Files

`.github/workflows/ci.yml` and this entry.
