# Release gate: the three intent rows are real-process tests (#258)

## What changed
The release gate's intent group is held by tests that start real processes and Godot
(`tests/release_gate/gate_intent.py`). The change used throughout is the seeded bug, a change of
behaviour that breaks the approved check "player stays above ground".

- **An approved intentional change passes as a contract change.** Declared an intended change
  (`--intent change`), the change is still rejected. Rewriting, in the same change, the check it
  breaks (tolerance 20 px to 100,000 px) does not help either: the checks come from the base, and the
  record says the change edits a spec that judges changes once it merges.
- **A weakened tolerance.** The same weakening, through `expectrail verify` with a base: rejected by
  the base's check.
- **A misleading generated check stays advisory.** A generated-checks block that reports eight valid
  generated checks and no catch leaves the reject a reject, and is shown in the record as it was
  given. A block whose counts disagree with its rows is read as "nothing generated" and changes
  nothing.
- **The pull-request gate's command, with both observers** (`tests/release_gate/pr_gate.py`). A
  change's intent and the generated block are inputs of `python3 -m expectrail.gate.verify` only; the
  orchestrator's command takes neither. This runs that command's own `main` with `run_gate` given the
  rule `both` and the recorded observer, as the release gate's worker does for the orchestrator. A new
  positive control shows this command clears the unchanged game declared an intended change.
- Each row's `scope` says what it does not cover: the orchestrator's command has no intent input; the
  positive side of a contract change (the new check approved first) is not run, because the recorded
  vision answers cover only the samples' checks; and without a base a change's own checks judge it,
  with nothing binding an approval to a check's content until #420.
- `docs/release-gate.md` regenerated: held 18, open 17, failed 0, not run 0.

## What was run
- `python3 -m tools.release_gate --out docs/release-gate.md` with these changes on main 9dc79d5,
  locally with real Godot 4.7.2 and no bubblewrap: 31 tests, OK in 663 s. Held 18, open 17, failed 0,
  not run 0.
- `python3 -m unittest tests.test_release_gate`: 15 tests, OK.
- By hand before the tests were written, the same scenarios through both commands. Two that are not
  kept as tests: the weakened bug with no base is needs-review, and the seeded bug judged by a base
  whose check is weakened is needs-review (the recorded answers do not cover the edited check).
- The full suite: see the pull request.
- No model was called; nothing was spent.

## Not done
- Reading a private path and network egress through the real command with the replay sandbox: they
  need bubblewrap, which this session could not install (`apt-get` finds no package here).
- Every row that waits on #254, #255 or #257, and disk quota.
- The release gate has not run in CI on this branch when this was written.

## Files
- `tests/release_gate/gate_intent.py` (new), `tests/release_gate/pr_gate.py` (new),
  `tests/release_gate/controls.py`
- `tools/release_gate.py`
- `docs/release-gate.md`, `docs/new-work/2026-11-14-release-gate-intent.md`
