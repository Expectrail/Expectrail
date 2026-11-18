# Closing-keyword links require a demonstrated repair (#284)

## What changed
PR closing-keyword references now imply fix, regardless of a none/change declaration.
Both CI halves use the same parser and keep the matched phrase and body line in
closed bundle/findings contracts. The legacy gate command uses its existing event;
report and comment readers show the source and refuse stale or downgraded evidence.
No issue API, permission change, new check or decision rule. See the full
[Done when audit](../linked-bug-fix.md) and [real-engine counts](../measurements/284-linked-known-bench.md).

Guard: test change intended (#284)

The existing closing-link assertion is made stricter (needs-review instead of
accept). An unrelated-reference case remains; no existing assertion was weakened.

## What was run
- Required historic fetch, once: `git fetch --no-tags --depth=1 origin c169a5e0da304773587304ed47bc8aabcec80da7` succeeded.
- Before changes, no EXPECTRAIL variables: `python3 -m unittest discover -s tests -t .`: 4,565 tests, 441.251s, OK (58 skipped), exit 0.
- Red run: initial 10 linked-source tests on the unchanged base failed (5 failures, 5 errors). Raw log in handover.
- Focused regression run: 201 tests, 21.984s, OK; final new-source run after reader guard: 17 tests, 3.110s, OK. Intermediate fixture/guard failures are retained in the handover and are not passing evidence.
- Real Godot 4.7.2-stable: `python3 -m tools.linked_bug_bench` on all eight public known cases, 16 gate judgments. Four wrong fixes: 4 accept before, 4 needs-review after. Four correct fixes: same transition; no approved base check reproduced any of these four bugs. Engine-only, headless, sandbox off, no model.
- Full final after suite, no EXPECTRAIL variables: `python3 -m unittest discover -s tests -t .`: 4,583 tests, 440.216s, OK (58 skipped), exit 0. An intermediate full run passed 4,582 tests in 449.765s; the final run includes the bounded event read and shallow-checkout fixture adjustment.
- Final new-source tests: 18 tests, 3.557s, OK. With numpy/PIL imports blocked and find_spec returning None: 42 intent tests, 3.693s, OK.
- `python -m agents.export_scan bench docs README.md apps --paths error`: 779 files, 0 errors, 0 warnings, exit 0. The spent blind folder entry was held aside unopened and restored; its contents were not scanned. An initial attempt to hold it aside across filesystems failed before the scan started; the successful attempt used the same filesystem.
- All 16 real gate findings passed the existing strict reader and matched their published bench rows. Binary patch applies to the recorded base and recreates the staged tree.

## Not done
No live model/vision/fixer calls, spend, dispatch, GitHub writes or push. No workflow,
approval, tracked game source, orchestrator CLI/request or held-out content changed.
No claim of CI execution, vision accuracy or sandbox security from the diagnostic
bench. Issue-label classification is optional future work; proposal only, no
permission change is needed for the conservative closing-link rule.

## Files
- Contracts and examples: `contracts/findings.schema.json`, `contracts/ci-bundle.v1.schema.json`, `contracts/examples/findings-linked-fix.json`, `contracts/examples/ci-bundle-linked-fix.json`.
- Writer/readers: `expectrail/gate/intent.py`, `expectrail/gate/record.py`, `expectrail/gate/comment.py`, `expectrail/gate/verify.py` (event metadata at CLI boundary only), `tools/ci_bundle.py`, `tools/ci_checks.py`.
- Tests and bench wrapper: `tests/test_gate_intent_from_pr.py`, `tests/test_linked_bug_intent.py`, `tools/linked_bug_bench.py`.
- Docs: `docs/ci-gate.md`, `docs/linked-bug-fix.md`, `docs/proposals/284-issue-labels.yml.txt`, `docs/measurements/284-linked-known-bench.json`, `docs/measurements/284-linked-known-bench.md`, this log.
