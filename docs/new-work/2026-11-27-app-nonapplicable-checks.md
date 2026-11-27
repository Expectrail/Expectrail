# Explain when no public check applies in Past runs (#370)

## What changed

Past runs now explains when all saved public check rows are marked
`not-applicable`. A job without a Before result can also have this outcome.
An applicable result on either side keeps the existing observer explanation.

## What was run

Hosted Linux CI passed the public gate tests
`test_nonapplicable_route_is_not_replayed_or_sent_to_the_observer` and
`test_only_nonapplicable_checks_do_not_make_an_accept`. The first checks that
no replay ran, the visual observer received no requests, and the gate returned
needs-review. The second checks that the result retains a row with
`after: not-applicable` while the public check count is zero.
[Hosted test log](https://github.com/Expectrail/Expectrail/actions/runs/45950555349/job/140345150230)

The queued app code on tree `eb810799` treats the presence of that row
as a reason to report the configured observers. The new app regressions
cover both Before forms, the three observer configurations, and a mix of
applicable and inapplicable rows.

## Not done

The app regressions and full discovery on the changed tree need a Linux run.

## Files

- `expectrail/app.py`
- `tests/test_app.py`
- `docs/new-work/2026-11-27-app-nonapplicable-checks.md`
