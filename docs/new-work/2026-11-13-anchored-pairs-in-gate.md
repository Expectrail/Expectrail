# The player's place on both sides, in the gate

## What changed

Part of #327, decision B. Under the rule `both` with a base, the gate asks the visual observer's
model what is drawn inside the player's own collision box (the trace's `body`, #369) in every tenth
captured frame of each route and its last, on both sides, and compares each head frame with the same
base frame (`agents.anchor_rule.pair_frame`).

- `expectrail/gate/anchor.py` (new): asks, compares, builds the record's `anchor` block, keeps the
  differing frames as `anchor/<route>/base-NNNNNN.png` and `head-NNNNNN.png`.
- `expectrail/gate/record.py`: `decide` takes the block; `anchor_effect` is decision B (a route that
  differs, a frame with no answer, or asking that stopped keeps the decision from accept; nothing
  rejects, nothing accepts); `check_anchor` holds a record's block to its own counts, to the rule
  `both` and to a judged base, and the reader recomputes the decision with it.
- `expectrail/gate/verify.py`: `judge_arm` can keep each replay; `run_gate` builds the block and
  writes it. `ANCHOR_EVERY` is 10.
- `expectrail/observers.py`: `FramesObserver.segmenter()` gives the client for box questions.
- `contracts/findings.schema.json`: the `anchor` block. `contracts/examples/findings-anchor-differs.json` (new).
- `docs/ci-gate.md` (new section "The player's place on both sides"), `docs/contracts.md`.

## What was run

- `python3 -m unittest tests.test_anchor_gate`: 19 tests, against stand-in replays that log the body
  box and a scripted model in SAM 3.1's wire format (not live answers). A player drawn half hidden is
  needs-review with both frames kept and the check itself passing on both observers; no answer is
  needs-review; a player the engine moved, or a harness without the body box, changes nothing; no
  base, no block; a reject stays a reject; the reader refuses an accept beside a difference and a
  block whose result or frames do not follow from its counts.
- `tests.test_two_observers` and `tests.test_ci_gate` unchanged and passing.
- The full suite on this branch: 2712 tests OK, 27 skipped.

No live model was asked through this path.

- After the guard's review of cc317f7: the frames that differ are listed first, so a route with
  more than 32 moved or unbased frames before its first difference still gives a block the reader
  accepts (a test with 40 moved frames, then 21 differing); routes past the schema's 256, or with
  names longer than 200 characters, stop the asking (never an accept); a test holds the writer's
  caps equal to the schema's. `tests.test_anchor_gate`: 22 tests. Full suite merged with main:
  2741 tests OK, 27 skipped.

## Not done

- The review page does not show the kept frames side by side yet; they are in the artifact.
- No command constructs a visual observer yet (as before), so nothing runs this in CI or in
  `expectrail verify` until the two-job action (#254) and the orchestrator pass one.
- The false-alarm rate on any game but the bundled one: blind test 4.

## Files

- `expectrail/gate/anchor.py`, `expectrail/gate/record.py`, `expectrail/gate/verify.py`, `expectrail/observers.py`
- `contracts/findings.schema.json`, `contracts/examples/findings-anchor-differs.json`
- `tests/test_anchor_gate.py`, `tests/test_package.py` (two modules named as imported only with a visual observer)
- `docs/ci-gate.md`, `docs/contracts.md`, `docs/new-work/2026-11-13-anchored-pairs-in-gate.md`
