# Frozen hosted trial handover (#254)

## What changed

Reused main's existing `tools.gate_trials` implementation. Exported all five
trial heads from one frozen main, the common public fall-through seed, a separate
new-head successor, one-line commit messages, PR bodies and exact expected App
check results. Every mailbox series starts from main and includes seed then head;
the included Git bundle preserves the prepared IDs. Git objects/refs were made
locally through the existing alternate-index tool, without checking out a game.

Added a complete Done when audit and person-only trusted-job snippets for the
post-download tamper and post-binding stale-head window. Push the seeded base
once; preserve any later trusted-workflow setup rather than re-pushing old base.
No contract or schema changed: existing CI bundle/findings writers/readers and
trial preparation formats are reused unchanged.

## What was run

- Read current AGENTS.md, #254 and all seven comments, existing trial implementation/guide, gate workflow and tests.
- Local `chatgpt/254-hosted-trials` from latest main `49226b6cdadda80754ecee1c61ed33116aeb9b6c`; supplied branch was already current. Required historic fetch succeeded once.
- Full before, no EXPECTRAIL variables: 4,700 tests, 839.374s, OK (60 skipped), exit 0.
- Existing trial, split-gate, head-check and workflow-safety tests: 48 tests, 8.134s, OK.
- Numpy/PIL imports and detection blocked: 32 trial/head-check tests, 2.337s, OK.
- Prepared all five trials with placeholder URLs for an existing disposable parent and fork; no printed push was run. Each two-commit mailbox series applied from main into a temporary index and exactly reconstructed its head. The separate successor also reconstructed. Bundle verification passed for seven refs. Normal index and tracked worktree stayed unchanged throughout preparation.
- Parsed both proposal steps: literal target/branch guards, completed-event and bound-state guards, zero secret references; no workflow edit.
- First full after: 4,700 tests, 824.142s, one failure, 60 skipped. Unchanged `tests.test_orchestrator.ProcessTest.test_waiting_on_a_worker_that_died_reports_it_at_once` took 0.5258s against its 0.5s limit. An unchanged isolated run also failed at 0.5389s; a later unchanged isolated run passed (1 test, 0.625s total). The measured diagnostic preserves the original cleanup/assertion and records three process scans of about 0.15–0.18s each on a host with over 11,000 PID-1 zombie children; this is diagnostic evidence, not a source fix.
- Final native full after retry, unchanged source/assertions, no EXPECTRAIL variables: 4,700 tests, 543.660s, OK (60 skipped), exit 0. All prior failure logs are retained.
- Both saved historical publisher fixtures replayed offline as historical accept / identity refusal.
- Required export scan: 851 files, zero errors/warnings, exit 0. Binary handover reconstruction is recorded in PATCH_VALIDATION.json. Read-only Docker probes were made while diagnosing the timing failure; no image was built/pulled and no container was started.

## Not done

Part of #254: all five new controlled hosted observations still need the architect
and Sean. No live model, spend, dispatch, push, PR, GitHub write, repository setup,
secret read or workflow/approval/game-source edit. No new assertion or skip; no
Guard line needed. Stand-in tests and old saved public publisher records do not
count as the required new hosted measurements. Branch enforcement additionally
requires a person to record settings and a blocked non-bypass merge.

## Files

- `docs/254-hosted-trials.md`: ready-patch instructions, expectations and exact case audit.
- `docs/proposals/254-hosted-controls.yml.txt`: person-only trusted-job insertion proposals.
- `docs/ci-gate.md`: link to the frozen trial handover/audit.
- This work log.
- The handover zip holds the five series, head-only diffs, seeded-base patch, successor, plans, seven-ref Git bundle, validations and logs; bulk preparation artifacts are not added to main.
