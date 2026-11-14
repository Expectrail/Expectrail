# Engine checks still run without vision settings (#379)

## What changed
Missing MODEL_API_KEY or EXPECTRAIL_SAM_USD_CAP no longer blocks replay. The gate keeps the
rule `both`. An engine failure rejects; a passing engine check cannot accept without vision.
Completed jobs retain PROVIDER_FAILED diagnostics naming the missing settings and fixes.
Doctor still requires both settings. There is no new command option or contract field.

The CI sample steps now require needs-review, reject, needs-review, and the installed second
project needs-review. They check saved findings, completed engine checks and sandbox accounting.
The package job installs Bubblewrap and uses the existing user-namespace setup so its sample
and second-project replays must also run in the sandbox. Doctor JSON and LostWorkerTest fixes
from a266c910453360d43b41ff9bdd713a0b03d5ee43 are retained.

## What was run
- `python3 -m unittest tests.test_verify_vision -v` before the fix: 5 tests, 10 failing subtests.
  They showed that missing settings prevented replay and hid engine failures.
- `python3 -m unittest tests.test_no_vision_ci -v` before its checker: 2 tests, 2 import errors.
- `python3 -m unittest tests.test_verify_vision tests.test_doctor tests.test_two_observers tests.test_orchestrator -v`:
  185 tests, OK (1 skipped).
- `python3 -m unittest tests.test_no_vision_ci tests.test_ci_vision tests.test_verify_vision -v`:
  11 tests, OK. These use stand-in engines and no live model.
- `python3 -m unittest discover -s tests -t .`: before 2,898 tests; after 2,902 tests.
  Each had 7 failures, 8 errors and 25 skips. All 15 failure/error names match exactly.
  The before tree contains the previous handover; its code and tests equal a266c91.
  Its only difference from that commit is an appended architect run note in the previous worklog.
- Built the wheel with `python3 -m pip wheel . --no-deps --no-build-isolation --no-index` and
  installed it in a clean venv. The three actual CI shell scripts passed against stand-in saved
  findings and refused an unexpected exit 0. Installed checks imported the installed package.
- `EXPECTRAIL_SANDBOX_TESTS=required python3 -m unittest tests.test_replay_sandbox.LostWorkerTest.test_a_killed_workers_sandboxed_replay_dies_with_it -v`:
  failed at setup: xvfb-run is absent. Godot 4.7.2 and Bubblewrap 0.12.0 run here, but Bubblewrap's
  probe also fails with NETLINK_ROUTE operation not permitted. No sandbox replay was proven.
- `python3 -m expectrail.capabilities render` and `python3 -m expectrail.capabilities check`: passed.

## Not done
No live model request or spend, GitHub write, commit or push. The real sandbox replay and the
three CI runs need a capable Linux host. CI is not claimed green. The architect must merge main,
resolve the capability ledger conflict, run the suite on that merge and wait for every CI check.
The handover includes logs, both patch bases and a checked ledger-resolution helper.

## Files
- `.github/workflows/ci.yml`
- `README.md`
- `contracts/examples/doctor.json`
- `docs/capabilities.json`
- `docs/capabilities.md`
- `docs/ci-gate.md`
- `docs/install.md`
- `docs/new-work/2026-11-13-engine-checks-without-vision.md`
- `docs/orchestrator.md`
- `expectrail/doctor.py`
- `expectrail/orchestrator/cli.py`
- `expectrail/orchestrator/engines.py`
- `expectrail/orchestrator/runner.py`
- `expectrail/orchestrator/sample.py`
- `tests/test_no_vision_ci.py`
- `tests/test_verify_vision.py`
- `tools/check_no_vision.py`

## Architect run (Linux)
On a266c91: before 2910 tests OK, after 2914 tests OK (27 skipped each). Focused `test_verify_vision test_no_vision_ci test_ci_vision`: 11 OK.

## The outside trial without vision (architect, after #401 merged)
`tests/outside/projects.json` now expects needs-review for kinematic_character harmless: with no vision key in CI, a pass by the engine is needs-review (#379). docs/outside-projects.md says so.
