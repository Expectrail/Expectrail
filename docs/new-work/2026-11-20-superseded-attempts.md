# A re-run concludes the clearance a lost runner left open (#254)

## What changed
If the trusted job's runner is lost, its finish step never runs, and the head's `Expectrail
clearance` stays `in_progress`. The check's own text says to re-run the verify workflow. Before this
change the re-run got new checks, but the lost attempt's checks stayed open beside them for ever.

Now, when the trusted job starts the checks for the latest capture of a head, it also concludes this
publisher's still-open checks on that head from earlier captures (a lower run id, or an earlier
attempt of the same run). Clearance ends `failure`, evidence `neutral`, with "Superseded capture or
pull request: a newer capture of this commit ran (expectrail/RUN/ATTEMPT) … This commit is not
cleared by it." An earlier capture could never clear anyway, because `finish` refuses any capture
that is not the latest.

Left alone: another app's checks, completed checks, a later key, and any check whose external id
cannot be read as `expectrail/RUN/ATTEMPT`. A capture that is itself superseded cleans up only its
own checks, as before. The clean-up is housekeeping: a refused update or a failed listing is printed
as a workflow warning and never stops the judging of this capture.

`tools/ci_checks.py` only. No workflow file changed.

## What was run
- `python3 -m unittest tests.test_ci_gate.HeadChecksTest`: 19 tests, OK (5 new).
- Seven mutations of `close_superseded` (comparison loosened twice, completed checks included,
  publisher filter dropped, evidence concluded `success`, the key matched by search instead of in
  full, refused updates not caught): each failed at least one test.
- The full suite on the branch merged with main: see the pull request.
- No hosted trial and no workflow run.

## Not done
- A lost runner on the latest capture, with no re-run, still leaves the clearance in progress. That
  never counts as cleared.
- Open checks left on an earlier head of the pull request by a lost runner are not swept. They do
  not gate the pull request, which is judged on its current head.
- Only the first 100 checks of each name on a head are looked at.

## Files
- `tools/ci_checks.py`
- `tests/test_ci_gate.py`
- `docs/ci-gate.md`
- `docs/new-work/2026-11-20-superseded-attempts.md`
