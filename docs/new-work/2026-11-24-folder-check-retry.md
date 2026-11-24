# Retry an interrupted folder comparison before creating a job (#803)

## What changed

If the local folder check fails, Verify leaves the job idle and shows how to
retry. The next click checks the same selected paths again. If both resolve to
one folder, the app focuses **Choose Before folder** and offers a baseline.
The developer can then choose a different Before folder or click Verify again.
Manual mode also offers that choice when the project uses explicit route and
check paths.

## What was run

On `c1c69616`, the new Chromium regression saw an unexpected `/api/inspect`
request after a connection reset on the folder check. The
[independent installed-wheel trial](https://github.com/Expectrail/Expectrail/pull/813#issuecomment-7126226110)
also recorded jobs started on the original click.

With the fix, `python3 -m unittest -v tests.test_app_desktop_chooser` passed
both tests on Chromium 156. The browser let the real server resolve the paths
and dropped the reply while Verify was waiting. It checked that the original
click sent zero inspection or job requests, and that a retry without changing
either field made another folder request. The retry showed the same-copy warning
and still sent zero inspection or job requests. A later click started a baseline.
The rehearsal covered both configured and manual inputs and retained the
distinct-folder controls.

## Not done

The job worker in the regression used the test replay backend. The measured
behavior was browser submission and recovery.

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/new-work/2026-11-24-folder-check-retry.md`
