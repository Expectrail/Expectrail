# Follow-ups from the merge guard's reviews of #310 and #312 (#253, #307)

## What changed
Five gaps the merge guard listed when it merged #312 (the gate's isolation record) and #310 (the
orchestrator), none of which made an accept easier than before those merged.

- **A record cannot count fewer replays than its checks rest on.** With the sandbox required, a record
  that counted no replays, or one replay for two routes, read as accept, so a replay outside the
  sandbox could be hidden by not counting it. The reader now needs at least one replay per judged
  route on each side that has a result, plus the held-out replays its counts imply.
- **A replay must name a tool the record knows.** An account with an empty `sandbox` counted as inside
  and the tool was written as "None", which the schema then refused. It now counts as outside with a
  plain reason. A replay that names another tool or version than the first is not counted with it.
- **The verify action changes the runner's kernel setting only when `require-sandbox` is `true`.** It
  did so on every run. On a self-hosted runner the setting stays until reboot; the docs say so.
- **An empty file is not evidence.** An accept or a reject needs a file with something in it.
- **The jobs-folder check also compares without regard to case**, since on macOS `RUNS/**` reaches
  `runs/jobs`. The first version of this change replaced the exact comparison with the case-folded
  one, which the merge guard showed to be a regression: folding a pattern's case changes what a range
  such as `[S-s]` holds, so `[S-s]uns/**` was no longer refused. The folded comparison is now added to
  the exact one, and a test holds the property over about ten thousand generated patterns: every one
  whose real glob finds a file below the jobs folder is reported as reaching it.

## What was run
- `python3 -m unittest tests.test_ci_gate tests.test_orchestrator tests.test_jit_rules`: OK.
- The full suite, merged with main: 1,993 tests, OK, 17 skipped (7 need bubblewrap).
- One test's fixture changed: the comment-size test builds a record with 64 routes and kept the
  example's count of 6 replays, which the new rule refuses; it now counts 130.
- Not run: the action's changed step on a self-hosted runner.

## Not done
- #307 gap 3 (a killed worker's children) and gap 7; #253's Unity and web replays.

## Files
`expectrail/gate/record.py`, `expectrail/orchestrator/store.py`, `expectrail/orchestrator/request.py`,
`.github/actions/expectrail-verify/action.yml`, `docs/ci-gate.md`, `tests/test_ci_gate.py`,
`tests/test_orchestrator.py`
