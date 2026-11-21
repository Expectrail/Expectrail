# A clearance left open by a lost trusted job is concluded failed by a later one (#254)

## What changed
- `tools/ci_checks.py`: `close_lost()`. When the runner of the trusted job that judges a head's
  latest capture was lost and nobody re-ran the capture, the head's **Expectrail clearance** stayed
  in progress for good. Nothing else could reach it, because no later trusted job ran for that head.
  Now any later trusted job in the repository (the start step, as housekeeping) looks at the heads of
  the 30 most recently updated open pull requests. It concludes this App's open clearance there as
  failed when that capture is a completed `pull_request` run of the verify workflow on the same
  commit that ended six hours ago or more.
  - It never concludes success. The evidence check was created concluded (neutral) and is left.
  - The job's own capture is never touched, and neither is another app's check, a completed one or a
    key it cannot read.
  - A capture run or a list of checks that cannot be read leaves those checks as they are, with a
    warning. A list of open pull requests that cannot be read sweeps nothing. In the start step any
    failure of the sweep only warns.
  - If the lost trusted job does run later, `start` finds the same check by its key and `finish`
    concludes it with its own result.
- `docs/ci-gate.md` says so in the paragraph on lost runners.
- `tests/test_ci_gate.py`: the stand-in API of the earlier-heads tests now answers a capture run's
  attempt as still running, so the start-step tests that expect no warning meet the new sweep and
  it decides nothing there. No assertion changed.

## What was run
- `python3 -m unittest tests.test_ci_lost_capture`: 14 tests, OK. With `tests.test_ci_gate`: 155
  tests, OK.
- Seven mutations, each caught, then reverted: concluding success; no time limit; a running capture
  counted; the job's own capture swept; the head not compared; the workflow not compared; a sweep
  failure stopping the start step.
- Full suite on the branch merged with main at 74d30c5: `Ran 5847 tests in 909.915s`,
  `OK (skipped=75)`.
- Not run against GitHub. No workflow was dispatched and no model was called.

## Not done
- The sweep runs only when another trusted job runs in the repository. On a repository with no
  other pull request activity, a lost clearance stays in progress (never cleared) until then or until
  the capture is re-run.
- A head beyond the 30 most recently updated open pull requests is not looked at.
- The new-head, tamper and fork trials on the trials repository (Sean's).

## Files
- `tools/ci_checks.py`
- `tests/test_ci_lost_capture.py`
- `tests/test_ci_gate.py`
- `docs/ci-gate.md`
- `docs/new-work/2026-11-21-lost-capture-sweep.md`
