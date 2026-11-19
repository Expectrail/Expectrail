# Show when a local verification stops before submission (#370)

## What changed

On an unconfigured Breakout project, clicking Verify left the progress line on “Checking the rendering environment before starting…” after inspection had already failed. The local app now says “Verification did not start” and shows the configuration error. If the connection drops after submission, the app sends the developer to Past runs to look for the job. When a known job loses its status connection, the app keeps Retry status and Cancel available.

## What was run

`python3 -m unittest tests.test_app_screens` failed on the old progress text and passed with the change (one Chromium test). The test also interrupts a known job's status poll and drops the reply after the server receives a submission.

I repeated Check folders and Verify in Chromium on two stock copies of Breakout at `0ac7aed444ea593a023d9b666c211d7ab8acd51e`. Both actions reported the missing configuration. The app submitted zero jobs and both project trees matched their starting hashes. [Original observation](https://github.com/Expectrail/Expectrail/issues/244#issuecomment-7003978280)

On main `8c2f9a2` with this patch, `python3 -m unittest discover -s tests -t .` ran 5,176 tests in 441.758 seconds and passed with 71 skipped. `python -m agents.export_scan bench docs README.md apps --paths error` checked 1,009 files with zero errors and zero warnings.

## Not done

Drafting a config still requires the terminal. The local app entry point for drafting is tracked in [#652](https://github.com/Expectrail/Expectrail/issues/652). The outside-project rehearsal used browser automation. A developer's unaided setup time remains unmeasured.

## Files

- `expectrail/app_page.py`
- `tests/test_app_screens.py`
- `docs/new-work/2026-11-19-local-app-preflight-status.md`
