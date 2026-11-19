# Preview an unconfigured Godot project in the local app (#370, #652)

## What changed

Check folders shows what the saved scenes say about each game folder. A missing configuration now has a setup preview with the starting scene, candidate player nodes, images and unresolved bindings. A pending draft must still match the current proposal and first route. Both folders can be inspected even when the first one needs setup. Verify still stops before submitting an unconfigured game.

## What was run

The new HTTP regression failed on main for the stock project, a saved draft and an invalid draft. It passed with the preview. It also checks that changing the saved route prevents a saved draft preview.
`python3 -m unittest tests.test_app_projects tests.test_app_screens` ran 14 tests successfully.

[Chromium rehearsal on pinned Breakout](https://github.com/Expectrail/Expectrail/issues/652#issuecomment-7018298018):
with a stock Before and a pending draft in After, Check folders identified both versions,
showed the starting scene and listed Paddle and Ball. Verify created zero jobs. The
file hashes of both project trees were identical before and after the browser session.
The same Chromium check passed outside the checkout with a wheel built and installed offline.

## Not done

Saving a configuration from the app and observing a developer use their own project unaided remain open on #652 and #370.

## Files

- `expectrail/app.py`
- `expectrail/app_page.py`
- `tests/test_app_projects.py`
- `tests/test_app_screens.py`
- `docs/app.md`
- `docs/new-work/2026-11-19-project-setup-preview.md`
