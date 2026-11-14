# The trusted judge workflow starts again

## What changed
After #429 merged, GitHub refused `.github/workflows/expectrail-comment.yml` as a whole. A step's `env` used `!cancelled()`, and status functions are allowed only in `if:`. The judge is started only by `workflow_run`, so it never started: every push recorded a failed run named after the file, with no jobs (runs 43572153616 to 43575964074). Pull requests got neither the evidence and clearance checks nor the verdict comment. The expression now uses `job.status != 'cancelled'`. A new test reads every workflow and refuses a status function in any expression that isn't an `if`.

## What was run
- `tests.test_workflow_expressions`: it fails on main (it finds `jobs/judge/steps/9/env/REPORT_READY`) and passes with the fix.
- `tests.test_ci_gate`, `tests.test_main_only_environment`, `tests.test_merge_guard`: OK.

## Not done
- Whether the judge then starts in the `main-only` environment from `workflow_run` (#247) is shown only by the first pull request after this merges.

## Files
- .github/workflows/expectrail-comment.yml
- tests/test_workflow_expressions.py
