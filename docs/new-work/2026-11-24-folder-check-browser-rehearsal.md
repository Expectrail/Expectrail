# Keep the next browser request observable during the folder rehearsal (#803)

## What changed

The folder-pair rehearsal holds the real comparison reply at the local HTTP
server until the developer clicks Verify. It checks the waiting message before
releasing that reply, and checks that the server received exactly one comparison
for the selected paths. Chromium handles the subsequent inspection and job
requests normally.

## What was run

The [hosted rehearsal](https://github.com/Expectrail/Expectrail/actions/runs/45335375022/job/138246097126)
timed out waiting for the distinct manual comparison's job response on
`6979ce45`. With the old rehearsal I reproduced a missed response in the manual
case on Chromium 153 and in the configured case on Chromium 157. In the latter
trace the page displayed the warning returned by inspection, although Playwright
timed out waiting for that inspection response. This happened when the rehearsal
removed its interception of the preceding folder request.

The revised `python3 -m tests.test_app_desktop_chooser` passed on Linux with
Playwright 1.63.0 and Chromium 157.0.8103.0, the browser version reported by CI.
It checked the early same-copy stop, the deliberate baseline, and the distinct
comparison in both modes, including the recorded folders and job count.

## Not done

The replay backend was a stand-in. The browser run exercised folder selection
and job submission.

## Files

- `tests/test_app_desktop_chooser.py`
- `docs/new-work/2026-11-24-folder-check-browser-rehearsal.md`
