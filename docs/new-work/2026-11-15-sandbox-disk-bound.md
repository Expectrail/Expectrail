# The replay sandbox bounds what a game writes to disk (#253)

## What changed
The replay sandbox let the game write to its work copy and output folder on the host's disk with
only a per-file cap, so a change could fill a runner's disk. Now `harness.sandbox.run` measures both
folders before the game starts, every 0.1 s while it runs, and once more after it ends. When the
game has added more than 4 GiB, or more than 250,000 files and folders, the sandbox is killed, what
it wrote is removed, and the replay fails. Anything that cannot be measured is refused, never let
through:

- a sparse file counts at its full length;
- links are counted as links and never followed;
- a folder the game makes unreadable gives "could not be measured", and the run is refused;
- a game that ends between two measurements is caught by the measurement after it ends.

The per-file cap stays as it was.

- `harness/sandbox.py`: `usage`, `watched` (the bound on any process), `run` hands its two writable
  folders to it, `DiskBoundError`, and `disk_bytes()`. `$EXPECTRAIL_SANDBOX_DISK_BYTES` can lower the
  byte bound and never raise it. `probe` keeps its plain trial run, which writes nothing.
- `harness/run.py`: a stop at the bound, in the import or the replay, ends the replay with "the
  replay was stopped: …". It removes the work copy and the output folder, making unreadable folders
  readable again first.
- `expectrail/gate/verify.py`: the record says in the gate's own words "the head replay was stopped:
  the game wrote more to its folders than the replay sandbox allows". It is a replay error, never a
  pass, and no text from the game reaches the record.
- Contract: `replay.json`'s `isolation.limits` gains `diskBytes` and `diskEntries` (schema, example,
  writer `describe`). Both are optional, so a replay from before the bound still reads.
- The release gate's "disk quota" row (#258) gets tests in place of its "undefended" reason:
  `DiskQuotaTest` in `tests/release_gate/gate_sandbox.py`. The control is the unchanged game carrying
  an autoload that writes 96 MB into its own folder. With the sandbox off, it writes all 96 MB and is
  cleared. In the isolated class with the bound lowered to 32 MB, it is stopped and not cleared, and
  its files are not kept.
- `docs/replay-sandbox.md` and the ledger row describe the bound and what it does not do.

The two record-reader gaps from the #312 review were already closed on main when this started, so
this change has no code for them. Their tests are already there:
- A record that counts fewer replays than its checks rest on is refused. See `tests/test_ci_gate.py`,
  "at least N replays".
- An empty `sandbox` dict is counted as outside the sandbox. See `tests/test_ci_gate.py`, "an empty
  sandbox".

## What was run
- `python3 -m unittest tests.test_replay_sandbox`: 56 tests, OK, 11 skipped. Most of the skipped
  tests need bubblewrap, which this machine does not have.
  - The file has 21 new tests: 14 in `DiskBoundTest` (real processes, no sandbox), 2 in
    `GateReasonTest`, 2 harness tests, 1 contract test, and 2 in `EscapeTest` (real bubblewrap).
  - 18 of them ran here and passed. 3 were skipped: the 2 bubblewrap tests, and the test of a folder
    made unreadable for real, because this session runs as root and root reads any folder. The mocked
    refusal covers that case here.
- `python3 -m unittest tests.test_release_gate`: 19 tests, OK.
- The disk quota row's control, with real Godot 4.7.2 and the sandbox off: 1 test, OK, 49 s. It wrote
  all 96 MB and was cleared.
- By hand, with real Godot and no sandbox: the bundled game carrying the filler, through `watched`
  with a 32 MB bound. Three runs, each stopped after 0.31 s with 202 to 227 MiB written, and no Godot
  left running. That is where "about 200 MB in 0.1 s" comes from.
- One measurement of a real replay folder (120 frames, 338 entries, 30 MB) takes 0.7 ms.
- The full suite on this branch: see the pull request.
- Not run: the two real-bubblewrap tests in `EscapeTest` and the isolated half of `DiskQuotaTest`.
  This machine has no bubblewrap and could not get one. Their first run is CI's `seeded-bugs` and
  `release-gate` jobs, which have bubblewrap and fail on a skip.

## Not done
- The Unity player and the web replay are still not sandboxed. They are the rest of #253.
- `docs/release-gate.md` is generated from a run of the gate. It still says "disk quota: open" until
  a run with bubblewrap regenerates it.
- The bound is a measurement, not a file-system quota. A quota would need a loop device or a
  memory-backed folder for the work copy. The first needs root, and the second costs memory equal to
  the bound.

## Files
- `harness/sandbox.py`, `harness/run.py`, `expectrail/gate/verify.py`
- `contracts/replay.schema.json`, `contracts/examples/replay.json`
- `tests/test_replay_sandbox.py`, `tests/release_gate/gate_sandbox.py`, `tests/release_gate/controls.py`,
  `tests/test_orchestrator.py` (its environment test now catches the sandbox tool's start at
  `box.watched`, where it now happens; the assertion is unchanged)
- `docs/replay-sandbox.md`, `docs/capabilities.json`, `docs/capabilities.md`,
  `docs/new-work/2026-11-15-sandbox-disk-bound.md`
