# Follow the quickstart with your own Godot game (#710)

## What changed

The quickstart now opens with the installed local app. A developer can choose the changed game, recognize or choose its earlier version, and inspect each folder. The instructions explain what to review when a setup is missing or only draft checks exist. The six command-line steps have their own heading.

## What was run

- Served the page on loopback with its checked-in assets. Chromium 156 displayed the two walkthrough headings, three app steps and seven named controls at 390 pixels with JavaScript disabled and at 1280 pixels with JavaScript enabled. Both documentation links resolved in the checkout. Neither viewport overflowed horizontally.
- Compared the six extracted command blocks and expected exits against the parent revision. They were identical.
- Ran `python3 -m unittest tests.test_quickstart tests.test_quickstart_ci tests.test_site_nav tests.test_app_desktop_chooser tests.test_app_project_picker`. All 28 tests passed, including the local app’s Chromium folder rehearsal.
- Rehearsed the instructions on two prepared copies of public Breakout with the Expectrail configs, routes and checks omitted. Using Chromium at 390 pixels and a native chooser stand-in, selected After, confirmed its Before sibling, checked both folders and chose the paddle in each player list. Both sides offered **Save draft setup…**. Stopping before save left both file trees unchanged and created zero jobs.

## Not done

This was an automated documentation and browser check. An unaided developer trial, a grant-judge walkthrough, native macOS and Windows runs, and end-to-end time to a verdict were not run here.

## Files

- `docs/quickstart.html`
- `docs/new-work/2026-11-22-own-game-quickstart.md`
