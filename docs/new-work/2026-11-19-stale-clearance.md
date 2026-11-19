# A superseded head's clearance is concluded failed, never left in progress (#254)

## What changed
The November 18 hosted trial on #254 (new head, Expectrail/expectrail-gate-trials#4) found the old
head's **Expectrail clearance** still `in_progress` 16 minutes after the second head was pushed.
The trusted job starts that check on the capture's `in_progress` event. On the `completed` event
it finds no open pull request at the old head (or a newer capture attempt) and returned without
touching the check.

`tools/ci_checks.py` now has `close_stale`. On a `completed` event whose capture is no longer the
pull request's current head or latest attempt, the trusted job judges nothing. It concludes the
checks it started for that run attempt: clearance `failure`, evidence `neutral`. Both summaries
read "Superseded capture or pull request: ... This commit is not cleared". It only touches checks
with this attempt's `external_id`, from the dedicated publisher, that are not yet completed. The
reason text is the one `tools/gate_trials` reads as an explicit stale refusal, so the ordinary
fast path of the new-head trial can now yield recorded stale proof. A test ties the two strings.

No workflow file changed. `docs/ci-gate.md`, `tools/gate_trials/README.md` and the new-head
expectation in `tools/gate_trials/build.py` say what now happens.

## What was run
- `python3 -m unittest tests.test_ci_gate.HeadChecksTest`: 9 tests, OK. Three are new: a head
  moved, a pull request gone and a newer attempt each conclude only this attempt's open checks,
  clearance failed; the `in_progress` event with no current pull request writes nothing; a closed
  stale check is never success.
- Five mutations of `close_stale` and its call were each caught by those tests: success instead
  of failure, no status filter, no publisher filter, no key filter, never called.
- `tests.test_ci_gate` and `tests.test_gate_trials`: 137 tests, OK.
- Full suite on the branch from main at a248982: 5,106 tests, OK, 63 skipped.
- Not run on GitHub: no hosted trial was repeated from this session.

## Not done
- Repeating the new-head trial on Expectrail/expectrail-gate-trials with this on its trusted
  default branch, to record the explicit refusal on a real pull request.
- If the trusted job's `start` step itself fails after creating the checks, the clearance can still
  be left in progress (`finish` has no state to work from). Not changed here.
- The tamper and fork trials.

## Files
- `tools/ci_checks.py`
- `tests/test_ci_gate.py`
- `tools/gate_trials/build.py`
- `tools/gate_trials/README.md`
- `docs/ci-gate.md`
- `docs/new-work/2026-11-19-stale-clearance.md`
