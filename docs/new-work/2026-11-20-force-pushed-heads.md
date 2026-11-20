# The earlier-heads sweep reaches a head that was force-pushed away (#254)

## What changed
When the trusted job starts the checks for the latest capture of a pull request's current head, it
already concluded this App's open checks on the pull request's earlier commits (#683). A head that
was force-pushed away is no longer among those commits, so a lost runner there left its clearance in
progress for good (never counted as cleared, but never concluded either).

`tools/ci_checks.py` now also reads the head commits of the verify workflow's newest 100
`pull_request` runs on the same head repository and branch (`run_heads`). Those heads come first,
then the pull request's own commits, and the newest 20 distinct ones are swept. A run of another
event, branch or head repository (a fork with the same branch name), or with a malformed head, is
skipped.

The fail-closed rules are unchanged. A commit that heads any open pull request is never touched, and
if the open pull requests or the pull request's commits cannot be read in full, nothing is swept. The
old path stays as the fallback: if the runs cannot be read, only the pull request's commits are swept
and the job prints a warning. No workflow changed. `docs/ci-gate.md` says what is and is not reached.

## What was run
- `python3 -m unittest tests.test_ci_gate.HeadChecksTest`: 33 tests, OK, 6 of them new: a
  force-pushed head is concluded (clearance failure, evidence neutral); a fork's commit with the same
  branch name, another open pull request's head and the current head are never read; runs of another
  event or branch or with a malformed head are skipped; an unreadable or failing runs list falls back
  to the commits and warns; an unreadable list of open pull requests still sweeps nothing; the start
  step passes the run through.
- Six mutations (no repository filter, no event filter, the run not passed from `main`, no open-head
  exclusion, commits ordered before run heads, run heads ignored) were each caught.
- Full suite on the branch with main at 990cf8d: 5,704 tests, OK, 75 skipped.
- No hosted trial was run.

## Not done
- A head older than the newest 100 runs on the branch is not reached.
- A lost runner on the latest capture of the current head, with no re-run, still leaves its
  clearance in progress (never cleared).
- The new-head, tamper and fork trials on the trials repository.

## Files
- `tools/ci_checks.py`
- `tests/test_ci_gate.py`
- `docs/ci-gate.md`
- `docs/new-work/2026-11-20-force-pushed-heads.md`
