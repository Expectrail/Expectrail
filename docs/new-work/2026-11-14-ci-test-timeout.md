# CI's test job gets 20 minutes, not 10

## What changed

- `.github/workflows/ci.yml`: the `test` job's `timeout-minutes` goes from 10 to 20. Nothing else in
  the workflow changes (triggers, permissions, secrets and environment are the same).
- Why: the full suite took 6 min 53 s on main's runner at cb1fc85, and on #423 it was cut off at 10
  minutes with 3,384 of 3,405 tests reported and none failed (job 132475142618). On the architect's
  machine the suite now takes about 10 minutes (3,415 tests, 611 s). A job cut off by the clock
  looks like a failure and costs a re-run.

## What was run

- `python3 -m unittest tests.test_workflow_expressions tests.test_ci_gate`: OK.

## Not done

- Making the suite faster. That is worth its own issue if it keeps growing.

## Files

- `.github/workflows/ci.yml`
- `docs/new-work/2026-11-14-ci-test-timeout.md`
