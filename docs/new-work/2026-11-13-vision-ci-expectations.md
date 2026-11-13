# CI vision expectations and the sandbox worker fixture (#379)

## What changed
The installed doctor step requires exit 3 and a valid JSON record with exactly vision-key
and vision-cap missing. It still checks the missing-engine fix and usage exit 5. No vision
disable flag or secret was added. The lost-worker test injects a test-only engine-only Gate
into its subprocess, preserving real Godot, the lease, process group and every assertion.
Four offline tests exercise the workflow script and the worker fixture configuration.

## What was run
- Pinned baseline fetch completed. Base is PR #392 head db44d4e646fad52181950b2c1f731071d343d5b6.
- `python3 -m unittest tests.test_ci_vision -v` before the fix: 4 tests, 1 failure and 1 error.
- `python3 -m unittest tests.test_ci_vision tests.test_verify_vision tests.test_package tests.test_replay_sandbox -v`:
  60 tests, OK, 8 existing environment skips.
- `python3 -m unittest discover -s tests -t .` before: 2894 tests, 7 failures, 8 errors, 25 skipped.
- The same full suite after: 2898 tests, 7 failures, 8 errors, 25 skipped.
  Failing/erroring names and multiplicities match exactly. Both logs are in the handover.
- Required LostWorkerTest before and after: failed at setup, not skipped. Godot 4.7.2 and
  Bubblewrap 0.12.0 are installed; xvfb-run is missing. The separate Bubblewrap probe also
  fails with NETLINK_ROUTE operation not permitted. No real sandbox replay was validated.
- Built and installed the wheel offline. Its doctor step rejects the additional missing display
  and skipped OpenGL checks here. Installed sample exits 3; second-project verify exits 2,
  both needs-review for missing vision settings. No model call was sent.

## Not done
Real sandbox replay and a successful installed doctor step still need a capable Linux host.
The later CI sample and installed second-project verify steps also expect success without
vision settings; they remain unchanged in this two-fix patch. No CI rerun, commit or push.

## Files
- `.github/workflows/ci.yml`
- `tests/test_replay_sandbox.py`
- `tests/test_ci_vision.py`
- `docs/new-work/2026-11-13-vision-ci-expectations.md`

## Architect run (Linux)
On the PR head db44d4e: before 2906 tests OK (27 skipped); after 2910 tests OK (27 skipped). Focused (`test_ci_vision`, `test_verify_vision`, `test_package`, `test_replay_sandbox`): 60 OK, 8 skipped. No bubblewrap here, so the required LostWorkerTest sandbox run and the installed doctor step are proven only by CI.
