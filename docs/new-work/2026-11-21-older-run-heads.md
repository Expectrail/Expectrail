# The earlier-heads sweep reads past the newest 100 runs (#254)

## What changed
The trusted job's earlier-heads sweep (`tools/ci_checks.py`, `run_heads`) read only the verify
workflow's newest 100 `pull_request` runs on the branch. On a branch with many re-runs of one head,
a force-pushed head older than those 100 runs was never reached, and its clearance stayed in
progress. Now the runs are read 100 at a time until the sweep's 20 distinct earlier heads are found
(the current head never counts), the list ends, or 10 pages (1,000 runs) have been read.

The first page that cannot be read still raises, and the sweep falls back to the pull request's own
commits with a warning, as before. A later page that cannot be read ends the reading with the
warning "Could not read every earlier capture" and keeps the heads already read. That is safe: the
sweep only ever concludes checks as failed or neutral, so a head it leaves out stays in progress,
which is never cleared.

`docs/ci-gate.md` says what is now reached and what still is not.

## What was run
- `python3 -m unittest tests.test_ci_gate`: 141 tests, OK. Four new tests in `HeadChecksTest`:
  a force-pushed head on the second page is reached; further pages are read only until the limit
  is met, and the current head never counts towards it; at most `RUN_PAGES` pages are read; an
  unreadable or malformed later page keeps page 1's heads, warns, and reads no further.
- Five mutations of `tools/ci_checks.py` were each caught by `HeadChecksTest`: one page only,
  counting the current head, raising on a later page, no early stop, and not passing the limit.
- Full suite on the branch merged with main: see the pull request.
- No workflow was dispatched. The sweep has not run on a real branch with more than 100 runs.

## Not done
- A head older than the newest 20 earlier heads, or than 1,000 runs, is still not reached.
- A lost runner on the latest capture, with no re-run, still leaves the clearance in progress.
- The new-head, tamper and fork trials on the trials repository.

## Files
- `tools/ci_checks.py`
- `tests/test_ci_gate.py`
- `docs/ci-gate.md`
- `docs/new-work/2026-11-21-older-run-heads.md`
