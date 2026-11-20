# The trusted job concludes open checks a lost runner left on a pull request's earlier heads (#254)

## What changed
When the trusted job starts the checks for the latest capture of a pull request's current head, it
now also concludes this checks App's still-open checks on the pull request's earlier commits (the
newest 20 besides the head): clearance `failure`, evidence `neutral`, "Superseded capture or pull
request: the pull request's head moved on to ..., ... This commit is not cleared." Before, a runner
lost on an earlier head left that head's clearance `in_progress` for ever.

An earlier head could never clear anyway: `finish` judges only the current head of the open pull
request. The sweep fails closed:
- a commit that is the head of any open pull request (this one's, or a stacked branch's whose
  capture may be judging now) is never read or touched;
- if the open pull requests or this pull request's commits cannot be read in full (not a list, a
  head without a 40-character sha, more than 1,000 open pull requests), nothing is swept;
- completed checks, other apps' checks and checks whose external id is not `expectrail/<run>/<attempt>`
  are left alone.

A failure of the sweep only prints a warning; it never stops the judging. A superseded capture
sweeps nothing. `tools/ci_checks.py` only; no workflow change. `docs/ci-gate.md` says what is and
is not covered.

## What was run
- `python3 -m unittest tests.test_ci_gate.HeadChecksTest`: 27 tests, OK (8 new). The two fake APIs
  that `main("start")` uses were taught the pull request commits listing (they return only the head),
  so the earlier tests see no earlier commits; no assertion changed.
- Seven mutations of `close_earlier_heads` and `open_heads` (no open-head exclusion, completed checks
  not skipped, oldest-first instead of newest-first, no page bound, unreadable heads accepted,
  clearance concluded `success`, external id not checked): each was caught.
- Full suite on the branch merged with current main: see the pull request.
- No hosted trial was run.

## Not done
- A head that was force-pushed away is not among the pull request's commits and is not reached.
- A lost runner on the latest capture of the current head, with no re-run, still leaves the
  clearance in progress (never counted as cleared).
- The new-head trial on the trials repository, and the tamper and fork trials.

## Files
- `tools/ci_checks.py`
- `tests/test_ci_gate.py`
- `docs/ci-gate.md`
- `docs/new-work/2026-11-20-254-sweep-earlier-heads.md`
