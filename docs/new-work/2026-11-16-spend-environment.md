# Paid runs wait for Sean's approval: model keys move to a `spend` environment (#265)

## What changed
Every job that uses a model key now declares `environment: spend` (38 jobs, 22 workflows): main
only, plus Sean's approval on every run. Jobs with only the held-out token or the signing key stay in
`main-only`. The central test holds the split; eleven per-workflow tests now expect `spend` for their
key jobs. See docs/spend-environment.md. This is the precondition for giving Run it its GitHub token.

## What was run
The sixteen workflow and environment test modules: OK. Full suite: see the pull request.

## Not done
Creating the environment and moving the secret values is Sean's (docs/spend-environment.md).

## Files
- .github/workflows/*.yml (22 files: environment lines only)
- tests/test_main_only_environment.py and eleven workflow tests
- docs/spend-environment.md, docs/run-it-deploy.md
