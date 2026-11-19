# A trusted job that crashes after starting its checks concludes them failed (#254)

## What changed
#636 left one way for **Expectrail clearance** to stay `in_progress`: the trusted job's `start`
step creates the two head checks, then crashes before it writes its judging state. `finish` runs
(`if: always()`), finds no state, and returned without touching the checks. A crash while
posting the pull request comment had the same effect, because `finish` concluded the checks only
after the comment call.

`tools/ci_checks.py`:
- `start` writes `gate-started.json` (this attempt's external id and the check ids) right after it
  creates the checks, before anything else can fail.
- `finish` on a `completed` event with no judging state calls `close_unfinished`: clearance
  `failure`, evidence `neutral`, summary "The trusted job stopped before it judged this capture.
  This commit is not cleared". It uses the recorded ids first. A check with no recorded id is
  found by its external id, as `close_stale` does. `finish` has no `CHECKS_APP` in its
  environment, so on that fallback a check another app owns is left alone: GitHub refuses the
  update (403 or 404), and that refusal is skipped. With `CHECKS_APP` set it is never tried.
- On the `in_progress` event `finish` still leaves the clearance open: the `completed` event
  judges it.
- If posting the comment raises, `finish` concludes the checks as needs-review (clearance
  `failure`) and then raises the error.

No workflow file changed. `docs/ci-gate.md` says what now happens.

## What was run
- `python3 -m unittest tests.test_ci_gate.HeadChecksTest`: 14 tests, OK. Five are new: a crashed
  start concluded by `finish`, with and without recorded ids; `start` records the ids before a
  crash; `finish` on the `in_progress` event writes nothing; the fallback skips completed checks
  and other apps' checks (refused by GitHub without `CHECKS_APP`, never tried with it); a failing
  comment still concludes the checks, clearance failed.
- Seven mutations were each caught: the ids not recorded, no `completed` guard, no publisher
  filter, the 403/404 refusal not skipped, no status filter, the comment error not caught.
- Full suite: FULLSUITE
- Not run on GitHub: no hosted trial from this session.

## Not done
- If the finish step never runs (a lost runner, say), the clearance still stays in progress. That
  never counts as cleared. Not tested: what GitHub does with `always()` steps on a cancelled job.
- The tamper and fork trials, and repeating the new-head trial, are still open on #254.

## Files
- tools/ci_checks.py
- tests/test_ci_gate.py
- docs/ci-gate.md, docs/new-work/2026-11-19-unfinished-clearance.md
