# Use arrow keys to choose a recent folder (#710)

## What changed

Choosing a recent folder used to fill the path field and immediately reset the menu to its placeholder. The next Down key picked the first folder again. The menu now keeps the selection while its value matches the path. Typing a different path still clears the selection.

## What was run

`python3 -m tests.test_app_desktop_chooser` failed on the second Down key before the fix. The Before field still showed “My game before” when the test expected “Another before”. The same rehearsal passed after the fix, including the check that typing a different After path clears the selection. It recorded six native chooser requests, zero jobs and zero page errors.

In a separate three-folder run on Linux with Chromium 156.0.8078.79, Down, Down, Down, Up selected the first, second, third and second folders in order. The app created zero jobs.

## Not done

This keyboard rehearsal covered Chromium on Linux. An unaided developer trial remains open.

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/new-work/2026-11-21-recent-folder-keyboard.md`
