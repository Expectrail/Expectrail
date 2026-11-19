# Show the compared folders in the local app result (#370)

## What changed
The result shows the Before and After folders saved in the job request. Opening a past run displays that run's folders even if the editable inputs have since changed. A new submission or an error hides the previous comparison.

## What was run
The Chromium screen test checks the displayed pair, clears the After input, gets a submission error, and reopens a past run. Before the change it failed because neither recorded folder appeared in the result.

After the change, the Chromium test passed. Full discovery with `python3 -m unittest discover -s tests -t .` ran 5,176 tests in 479.685 seconds, OK (71 skipped). The public export scan checked 1,008 files with zero errors or warnings.

## Files
- expectrail/app_page.py
- tests/test_app_screens.py
- docs/new-work/2026-11-19-app-result-folders.md
