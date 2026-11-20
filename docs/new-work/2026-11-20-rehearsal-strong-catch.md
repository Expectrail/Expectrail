# The generated-checks rehearsal covers a strong catch again (#691)

## What changed
Since the do-nothing control (#675, #686), the PR rehearsal in `jit.yml` no longer showed a strong catch:
the air-jump stand-in's only catching check passes a frozen player and is dropped. This adds a third case
that brings that coverage back, without touching `assess.validity`, the control or its three runs.

- `gun-cooldown-long-comment-only`: the public bench defect `gun-cooldown-long` (cooldown 1.5 s instead of
  0.3 s) is the base, and the candidate is a comment-only "fix", one comment line in `player/gun.gd`
  (`bench/jit/rehearsal/gun-cooldown-long-comment-only.patch`).
- Its stand-in proposal (`bench/jit/rehearsal/gun-cooldown-long-comment-only/jit-proposal.json`) holds the six
  checks the hosted baseline record proposed for that defect (run 43465090517, `bench/jit/recordings/...
  /repro-gun-cooldown-long/jit-run.json`), copied unchanged. A test holds them equal to the record.
  `docs/measurements/675-do-nothing-control.md` had already measured them failing the control; that is why
  this defect was chosen, so the case shows the plumbing, not a detection rate.
- `tools/jit_rehearsal_check.py` asserts, for this case, a strong catch by a valid check that the do-nothing
  control failed 3 of 3 and that failed 3 of 3 on the bug build and on the candidate. A catch whose control
  run was indeterminate, a weak catch, or a valid check that passes the control all fail the case.
- `jit.yml`'s rehearsal matrix now names each case's report and base, and has the third case. A test holds
  the matrix to the cases the check knows and to files that exist.
- `docs/jit.md` says the coverage is back.

## What was run
- The workflow's own command for the new case, on Godot 4.7.2 (SHA-512 checked by `harness/get_godot.sh`),
  in this session: `status complete`, `proposed 6, valid 6, strong 6, weak 0`, 72 replays, 404 s. Every check
  passed the clean game 3 of 3, failed the do-nothing control (`do-nothing:projectile`) 3 of 3, killed the
  base, and failed the comment-only candidate 3 of 3. No model was called (`sparkUsd 0`, `promptTokens 0`).
- `python3 -m tools.jit_rehearsal_check gun-cooldown-long-comment-only <that run's jit-run.json>`: "reached
  what it rehearses (valid 6, strong catches 6, each failed by the do-nothing control)", exit 0.
- `tests.test_jit_rehearsal_check`: 21 tests (12 new), OK. Seven mutations of the new check were each caught.
- The full suite on the branch merged with main: see the pull request.
- The rehearsal job in CI on this pull request: not yet run when this was written.

## Not done
- No exact-undo companion for gun-cooldown-long: the air-jump exact undo already rehearses "no catch".
- Air-jump itself still has no stand-in that survives the control.

## Files
- `.github/workflows/jit.yml`
- `bench/jit/rehearsal/gun-cooldown-long-comment-only.patch`
- `bench/jit/rehearsal/gun-cooldown-long-comment-only/jit-proposal.json`
- `tools/jit_rehearsal_check.py`
- `tests/test_jit_rehearsal_check.py`
- `docs/jit.md`
- `docs/new-work/2026-11-20-rehearsal-strong-catch.md`
