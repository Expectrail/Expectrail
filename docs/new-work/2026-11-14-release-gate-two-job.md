# Release gate: the two rows that waited on the two-job gate, run through the capture and the trusted judge (#258)

## What changed
- `tests/release_gate/bundle.py` runs the two halves of the pull-request gate since #254 as separate
  processes: `capture` is `tools.ci_bundle.capture` (the candidate job: base and head replayed in the
  replay sandbox, one archive with a manifest), `judge` is `tools.ci_bundle.judge` (the trusted job: the
  archive taken as data, checked against the base, judged with both observers; the visual observer
  answers from the "Run it" recordings), and `finish` is `tools.ci_checks.finish` (the step that completes
  the head's "Expectrail evidence" and "Expectrail clearance" checks) against a stand-in for GitHub's API.
- `tests/release_gate/gate_bundle.py` holds two rows with real Godot replays:
  - **writes to evidence or policy**: a frame, a trace, or a trace with its replay record rewritten in
    the archive between the jobs, a run taken out, an archive made under other checks: each is refused
    as `EVIDENCE_MISMATCH` and decides nothing. The seeded bug carrying a weakened copy of its check is
    judged by the base's check and rejected.
  - **changed head**: the judged accept is clearance for the head that was judged (the control), and
    not when the pull request has a new head or the candidate workflow has a newer attempt; a capture
    for the old head is refused for the new one.
  - Positive controls of their own: the judge clears the unchanged game's capture and rejects the
    seeded bug's.
- A row may name positive controls of its own (`baselines` in `controls.py`). The two-job rows need the
  replay sandbox, so a machine without bubblewrap reports them "not run" while the other rows are still
  read; the summary says so on its own line.
- "A forged trace" stays open with a new reason: the judgment left the candidate job, but the game still
  runs in the process that writes the trace.
- Found while writing the rows: the judge never compares the captured game trees with the commits it
  judges (#467). The row's scope says so.

## What was run
- The full suite on this branch at main 191cc3d: `python3 -m unittest discover -s tests -t .`, 3,576
  tests, OK, 31 skipped.
- `python3 -m tools.release_gate` locally with real Godot and no bubblewrap: 31 tests, OK, 5 skipped
  (the three two-job classes and the two sandbox classes). Held 18, open 13, failed 0, not run 4. That
  run wrote `docs/release-gate.md`.
- `python3 -m unittest tests.release_gate.gate_bundle` locally with a stand-in for bubblewrap, written
  for this check and not committed: the replays ran outside any sandbox and their records were made to
  say they ran in it, because the capture refuses anything else. 12 tests, OK, in 2 min 16 s. That shows
  the tests' logic and the judge's answers. It shows nothing about the sandbox.
- The real first run of the 12 tests in the sandbox is CI's `release-gate` job on this pull request,
  which has bubblewrap and fails on any skip.
- Nothing spent, no model called.

## Not done
- The hosted run on a test pull request (#254, Sean's): GitHub's artifact digest (`ci_checks.download`)
  and the real check runs are not exercised here.
- The rows that need #255 (receipts), #257 (the observation timeline) and #253 (a job's disk quota).
- `docs/release-gate.md` is written from a local run, where every test that needs bubblewrap is
  "not run".

## Files
- `tests/release_gate/bundle.py`, `tests/release_gate/gate_bundle.py` (new)
- `tests/release_gate/controls.py`, `tools/release_gate.py`, `tests/test_release_gate.py`
- `docs/release-gate.md`
- `docs/new-work/2026-11-14-release-gate-two-job.md`
