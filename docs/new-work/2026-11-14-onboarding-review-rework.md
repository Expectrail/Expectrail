# Resolve the onboarding review against current main (#331)

## What changed
Replaces #485. Prepared a resolved merge of current main into the reviewed
branch, removing the criss-cross integration ambiguity. The CLI, init message
and wheel list equal main plus only the review additions specified by the guard.
The review implementation and its tests are unchanged. The first-user kit now
distinguishes generating the HTML file from opening it.

The architect's protections remain: downloads are drafts with no approval, the
review refuses already approved configs, and main's gate still prevents a draft
from grounding an accept. No approval or gate implementation was changed.

## What was run
The handover's Git integration regressions fail the old head's ancestry and
diff-scope cases and pass the prepared merge. Two additional checks preserve the
exact additive integration and the architect's protections. These checks live
with the handover because they test specific Git history, not product behavior.

The untouched baseline ran 3,605 tests: two failures, zero errors, 46 skipped.
Both failures were `test_summary_counts_outcomes_per_condition` in
`tests.test_matrix.MatrixTest` and `tests.test_matrix.HeldOutMatrixTest`. An
immediate unchanged focused rerun passed both. This uses synthetic test fixtures,
not held-out material. The logs retain the failures; no matrix test was changed.
Final full-suite results and the comparison by name are in the replacement PR
and handover.

Final full suite: 3,698 tests in 357.875 seconds, OK
(41 skipped); zero failures and errors. Compared failing test names
with the retained baseline: no new failures.

## Not done
No human timing, new browser trial, real-engine replay, hosted CI, live model or
spend. No commits or pushes: the architect must commit the prepared merge with
both parents, then GitHub can assess the replacement branch's mergeability.
The earlier three-game/browser evidence belongs to #485's original run and is
not claimed as a new run here.

## Files
The eight original review files remain the feature diff: `docs/first-user-test.md`,
`docs/new-work/2026-11-14-onboarding-binding-review.md`, `expectrail/cli.py`,
`expectrail/onboard.py`, `expectrail/onboarding.py`, `setup.py`,
`tests/check_onboard_games.py`, and `tests/test_onboard.py`. This new work log is
the only additional path. None of #482's already-merged implementation is
reintroduced as a competing change.
