# Record the bundled combat route for the trusted CI judge (#444)

## What changed

The existing recording workflow accepts a target: the three original Run it samples
or gate-combat. The new target copies the unchanged bundled game, combat route and
CI's approved specs, judges every captured frame and compares clean against clean
to record the paired player-box questions too. It is not a website sample.

The CI reader loads the trusted base checkout's recording folder, with its configured
clean recording first. Exact frame/prompt keys only; primary answers win duplicates.
Existing sample recordings supply the clean smoke box answers; gate-combat adds the
missing combat answers. Bad files, mislabelled targets and mixed models fail closed.
The judge workflow and verdict rules are unchanged. The existing two recording jobs
keep their permissions, environment and secret references. CLI --sample aliases remain.

## What was run

Required fetch and current main fetch; base 7069378cdd2b41911e41691812a46fe65a1417df.
Before full suite: 3,594 tests, zero failures/errors, 46 skips, 373.455 seconds.
Focused tests: 53 tests, OK. The new offline test records all 90 combat frame answers
and 10 sampled box answers, accepts through the real two-observer gate and restores
not-recorded/needs-review when the recording is removed. No live model or engine.
The synthetic contract example passes check-recording --target gate-combat.
Initial focused runs exposed an unquoted colon in a new YAML description; quoted it
without changing an assertion. Logs are retained. An initial after-suite attempt exhausted disk: 3585 tests, 33 failures, 1012 errors, 41 skips. The handover retains that failed log. Removed only identified completed synthetic fixtures and regenerable bytecode caches before rerunning the same code.

Full-suite comparison: Before: 3594 tests, 0 failures, 0 errors, 46 skips, 373.455 seconds. After: 3605 tests, 0 failures, 0 errors, 46 skips, 376.736 seconds. Failure/error-name lists are both empty; no new failure.
Patch application to the named base, byte comparison, diff whitespace check and ZIP checksums passed.

## Not done

No dispatch, model call, spend, account change, approval, commit, push or GitHub write.
No real gate-combat recording is included. Sean must dispatch Run it record on main
with target=gate-combat and sam_usd_cap=1.00, approve the existing main-only run, then
review/merge its proposed recording. No claim of real CI clearance before that.
The recording PR is judged from its base policy, so its own answers do not clear it.
No approved check, game, route or forbidden file was changed. Actionlint is not installed;
YAML, shell preflight and workflow authority boundaries are tested offline instead.

## Files

- .github/workflows/run-it-record.yml
- contracts/vision-recording.v1.schema.json
- contracts/examples/vision-recording-gate-combat.json
- expectrail/runit.py
- expectrail/recorded.py
- tools/ci_checks.py
- tests/test_runit_record.py
- tests/test_combat_recording.py
- docs/run-it.md
- docs/new-work/2026-11-15-combat-recording.md
