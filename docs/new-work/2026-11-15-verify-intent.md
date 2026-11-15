# Verification requests carry repair intent (#284, part 1)

## What changed
`expectrail verify` accepts `--intent fix|change|none` (default `none`) and
`--bug TEXT` or `--bug @FILE` with `fix`. `@@` escapes a literal leading `@`.
The report is captured as bounded UTF-8 text before a job starts. It is context,
not a generated or approved check, and no URL is fetched. Requests and job status
carry the declaration; its text participates in the idempotency digest.

The existing orchestrator Gate already passes intent to `run_gate`. Its shared
`expectrail.gate.record.decide` still makes every decision, including three base
failures and three head passes for a demonstrated repair. No gate decision code,
`expectrail/gate/verify.py`, or top-level `expectrail/cli.py` changed. A missing
demonstration remains needs-review with `repair-not-demonstrated`; the CLI report
leads with “No check reproduced the reported bug, so this fix is not verified”.
Default requests and their digests remain unchanged. Existing fix requests without
a bug report (including repair callers) remain valid.

Both request and status contracts have examples and validated writers/readers.
Report files must be regular files, not links or pipes, and fit the input limits.
A request that expands past the worker's JSON limit is refused before queuing.

The viewer already displays the findings' declared intent and repair result.
With Sean's approved scope exception, its reproduction command now preserves
intent and the captured report, including @ prefixes, option-like text, quotes
and newlines. Both exports keep the complete command while retaining redaction;
prose clipping can no longer silently remove these flags.

## What was run
Unchanged main `6bcab934375c58817ffc723618dba87c3157ae9e`: full suite, 3,694 tests,
OK (41 skipped). The first 12 regressions on unchanged main: 7 failures and 3
errors, retained in the handover. The focused request, CLI and gate run passed:
59 tests, OK in 6.899s. After the approved viewer change, all 16 new tests plus
viewer, timeline and measurement tests passed: 57 tests, OK in 8.127s.
An intermediate full run found the new schema patterns lacked samples in the
existing pattern registry (one failure). Two samples were added; no existing
sample or assertion changed. The schema/intent run then passed: 26 tests, OK in
4.353s. The intermediate failure log is retained separately from the final run.

The public CLI tests run the actual request store, worker, Gate, observations,
evaluator and shared decision code. Only worker launch, replay and model transport
are stand-ins. Disposable game copies receive the seeded fall-through bug and its
fixture fix, or the public known-air-jump comment-only patch. Cases cover stable
repair, all checks passing on the base, an unresolved bug, a flaky base, default
and explicit none, change, missing base, unavailable vision, detached request,
report file snapshot, validation and idempotency. These are offline logic tests,
not new measured game results. Final full suite: 3,710 tests in 418.105s,
OK (41 skipped), versus baseline 3,694 tests in 402.001s, OK (41 skipped).
Both have zero failures and zero errors. Failing test names before: none;
after: none; new failures: none. The comparison and full logs are in the handover.

## Not done
No real-engine replay, live model, spend or new hosted CI run. The installed Godot
version differs from the pinned version; Chromium is unavailable (named suite skips).
No check was approved and no bundled game or bench evidence was edited.

Part 2 is not built: Sean must add `issues: read` to `jobs.judge.permissions` in
`.github/workflows/expectrail-comment.yml`, retaining its existing permissions,
and separately wire trusted linked-issue classification into the judge and
comment path. No workflow, token scope, secret or environment was changed.

Sean posted the claim and pushed the starting branch after local write attempts
were denied. Since his instruction to work locally, no GitHub comment or push
was attempted. This handover contains no new commit and no pull request was opened.

## Files
- `contracts/verify-request.v1.schema.json`
- `contracts/verify-job.v1.schema.json`
- `contracts/examples/verify-request-fix.json`
- `contracts/examples/verify-job-fix.json`
- `expectrail/orchestrator/request.py`
- `expectrail/orchestrator/store.py`
- `expectrail/orchestrator/cli.py`
- `tests/test_verify_intent.py`
- `tests/test_schema_pattern.py` (two new pattern samples; assertions unchanged)
- `expectrail/viewer.py` (approved reproduction-command exception)
- This work log.
