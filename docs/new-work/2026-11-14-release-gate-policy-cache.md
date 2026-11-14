# Release gate: a swapped policy and a poisoned import cache are real-process tests (#258)

## What changed
Two more rows of the release gate are held by tests that start the real `expectrail verify`, its
worker and Godot.

- **Swapped policy** (`tests/release_gate/gate_identity.py`). A job is created, so it names the
  digest of its checks, and its worker is held before it begins. The check is then weakened in the
  checkout it is read from (tolerance raised from 20 px to 100,000 px): in the head when there is no
  base, in the base when there is one. Released, the worker finds another digest and judges nothing:
  needs-review, `INPUT_INVALID` "the game or its checks changed after the job was created", no output.
  The control: the same swap put back byte for byte before release is cleared.
- **The hold** (`tests/release_gate/worker.py`). When `EXPECTRAIL_RELEASE_GATE_HOLD` names a file,
  the release gate's worker waits while it exists, at most 120 s, before running the orchestrator's
  unchanged `runner.work`. It is test code only; nothing in `expectrail/` changed.
- **A poisoned import cache** (`tests/release_gate/gate_interference.py`). The poison: in a `.godot/`
  import cache the robot's imported picture is replaced by the enemy's. The control puts that poison
  in the verifier's own cache with its key unchanged: the unchanged game is then not cleared, because
  its frames are not the recorded ones (`not-recorded`). A change that carries the same poison as
  `game/platformer/.godot/` in its checkout is judged on its source: the unchanged game is cleared
  with every vision question answered from the recording, and its head tree is the unchanged game's;
  the seeded bug with the poison is rejected.
- A row can carry a `scope`, printed after "held" to say what the held row covers and what it does
  not. The poisoned-cache row says that a run without the replay sandbox can still write the
  verifier's own cache.
- `docs/release-gate.md` regenerated: held 15, open 20, failed 0, not run 0. (The unreachable-route
  row was already held on main; the published file was older than that.)

## What was run
- `python3 -m tools.release_gate --out docs/release-gate.md` on 2a27951, locally with real Godot
  4.7.2 and no bubblewrap: 25 tests, OK in 644 s. Held 15, open 20, failed 0, not run 0.
- `python3 -m unittest tests.test_release_gate`: 15 tests, OK (two new: the scope note, the hold).
- The full suite on the branch (main is at 5433b5e, the branch's base): 3,334 tests, OK, 31 skipped.
- One probe by hand, not kept as a test: the weakened check asked for afresh on the seeded bug is
  needs-review (the recorded observer has no answers for its questions), not an accept.
- No model was called; nothing was spent.

## Not done
- Reading a private path and network egress through the real command with the replay sandbox. They
  need bubblewrap, which this session could not install; CI's `release-gate` job has it.
- The intent rows, and every row that waits on #254, #255 or #257.
- The release gate has not run in CI on this branch when this was written.

## Files
- `tests/release_gate/gate_identity.py`, `tests/release_gate/gate_interference.py` (new),
  `tests/release_gate/worker.py`, `tests/release_gate/common.py`, `tests/release_gate/controls.py`
- `tools/release_gate.py`, `tests/test_release_gate.py`
- `docs/release-gate.md`, `docs/new-work/2026-11-14-release-gate-policy-cache.md`
