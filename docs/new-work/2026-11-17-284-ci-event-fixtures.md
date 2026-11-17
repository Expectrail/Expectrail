# Isolate the two local-command exit-code fixtures (#284 / PR #588)

## What changed

Both tests now clear only `GITHUB_EVENT_PATH` for their local command fixtures.
Their synthetic PR identities deliberately do not identify the PR running CI.
All assertions, exit codes and production identity checks remain unchanged.
The separate EventCLI test still requires a mismatched event to refuse with code
3 without starting verification. `docs/ci-gate.md` now states the existing codes
and separates a stopped verification from a refusal before verification.
No wire format changed; contracts/examples/writers/readers are unchanged.

Guard: test change intended (#284)

Reason: scope the two local-command fixtures to local context. Inheriting the
runner's real PR event exercises the new identity refusal instead of their
original assertions. Neither assertion was removed or weakened.

## What was run

- Fresh PR head `c987db8c8024030daf09cb886558ee5cb57d6dca`, integrated with main `49226b6cdadda80754ecee1c61ed33116aeb9b6c` without conflicts. The handover patch contains only this fix, not the integration diff.
- Required historic fetch succeeded once.
- Before editing: full merged-tree suite, no EXPECTRAIL variables: 4,718 tests, 550.083s, OK (60 skipped).
- Red: the two unchanged tests with a synthetic surrounding CI PR event both fail with exactly the reported `3 != 2` and intent-map mismatches. Without that event both pass (2 tests, 0.209s).
- Green: the same two tests with the same surrounding event: 2 tests, 0.265s, OK.
- Focused tests including the separate valid/mismatched event cases: 5 tests, 0.172s, OK.
- Full after on the merged tree, with the synthetic surrounding CI event and no EXPECTRAIL variables: 4,718 tests, 651.329s, OK (60 skipped), exit 0.
- Numpy/PIL imports and detection blocked: 38 tests, 3.914s, OK.
- Required export scan: 854 files, zero errors/warnings. Binary patch applies cleanly to both the merged baseline and original PR head; the merged index reconstructs exactly.

## Not done

No exit-code contract change, CLI help change, production code change, observer
edit, workflow, approval, game source, onboarding, app or capability change.
No live model call, spend, dispatch, push or GitHub write.

## Files

- `tests/test_ci_gate.py`: clear the enclosing event in the local CLI test.
- `tests/test_gate_intent.py`: the same isolation for the intent CLI test.
- `docs/ci-gate.md`: existing command exit-code contract and CI/local distinction.
- This work log.
