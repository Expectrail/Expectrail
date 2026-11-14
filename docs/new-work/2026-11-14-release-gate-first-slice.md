# The release gate suite, first slice: operations, coverage and one identity control (#258)

## What changed
`tests/release_gate/` holds the release gate: one row per control of #258's table (35 rows, with
"dropped, duplicated, out-of-order frames" as three), in `controls.py`. Each row has real-process tests
that assert clearance is not granted, or an `open` reason. `python3 -m tools.release_gate` runs every
test in the `gate_*.py` modules and writes `docs/release-gate.md` from the results; a row is held only
when its tests ran and passed. A new CI job, `release-gate`, runs it with Godot and `--require` (a
skipped test fails it) and keeps the summary.

Held in this slice (10 rows): timeout, cancellation, a killed worker, retry, duplicate requests
(a key used for one change does not clear another; the same request twice at once is one job), an
empty suite, zero evaluations, a skipped required observer, a missing private suite, and an approval
added by the change. Each starts the orchestrator's command line, its worker and a real Godot replay,
and checks that nothing of the job is left running. A positive control (the unchanged game is cleared,
the seeded bug rejected, through the same command) runs with them; if it fails, no row is held.

Since #379 (#392) a run without a vision key accepts nothing, so the suite's command and worker
(`tests/release_gate/worker.py`) are the orchestrator's own with one difference: the visual observer
answers from the "Run it" samples' recorded answers (docs/run-it/vision/), keyed by frame SHA256 and
prompt. No model is called.

Found while writing it: a route whose every input names an action the game lacks is replayed with
the player standing still, and nothing says so; on main before #392 it was accepted. Filed as #417;
the "unreachable route" row is open with a probe that is an expected failure until then.

## What was run
- `python3 -m tools.release_gate --require --out docs/release-gate.md` on this branch (main at
  41364bd plus this change), real Godot 4.7.2, no bubblewrap here: 14 tests, OK (1 expected
  failure); held 10, open 25, failed 0, not run 0. The committed `docs/release-gate.md` is that run.
- `python3 -m unittest tests.test_release_gate`: 12 tests, OK.
- The full suite: see the pull request.
- The `release-gate` CI job: not run when this was written.

## Not done
The other 25 rows: most need #254 (the trusted job), #255 (the signed receipt) or #257 (the
observation timeline); disk quota is undefended (#253); provider outage and budget exhausted are next,
now that #379 put the visual observer on this path; swapped policy, a poisoned import cache, a
private path, network egress and the intent rows are not written yet.

## Files
- `tests/release_gate/__init__.py`, `controls.py`, `common.py`, `worker.py`, `gate_operations.py`,
  `gate_coverage.py`, `gate_identity.py`
- `tools/release_gate.py`
- `tests/test_release_gate.py`
- `docs/release-gate.md`
- `.github/workflows/ci.yml` (the `release-gate` job)
- `.gitignore` (lets `tools/release_gate.py` in)
