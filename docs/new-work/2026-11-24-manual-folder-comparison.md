# Show the same-copy warning before a manual verification starts (#803)

## What changed

The first Verify click in **Enter paths manually** could create a job before the
folder check returned. When both fields pointed to the same Godot folder, the
warning appeared after the job had started. Both manual and configured runs now
wait for the pending comparison. If it identifies one copy, the app shows the
warning and focuses **Choose Before folder**. A second click can start a baseline.
A distinct pair continues on the first click.

## What was run

On `20f60d29`, Chromium 156 submitted job `9dbe987720cf13b38f3308e7e09efab7`
while the same-copy notice was empty. The rehearsal used a temporary Godot
project with explicit route and check paths and no config file. It held the
real folder-check reply until after the click to make the ordering repeatable.
The added regression failed on that revision because it saw one `/api/jobs`
request while it expected none.

With the change, `python3 -m unittest -v tests.test_app_desktop_chooser` passed
both tests. The manual-path case saw zero inspection or job requests from the
early click. A deliberate second click started one baseline job. Changing
Before to a different directory then started one comparison on the first click.
The test checked the input folders saved for each job.

## Not done

The browser used the test replay backend. These runs measured selection and
submission. The gameplay clearance decision and independent review remain on
[PR #813](https://github.com/Expectrail/Expectrail/pull/813).

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/new-work/2026-11-24-manual-folder-comparison.md`
