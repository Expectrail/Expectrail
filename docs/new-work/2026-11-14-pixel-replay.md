# The replay judges pixel checks, and the run record carries them (#286)

## What changed
Under the pixel setting (`signals-reach-evidence-pixel`), `run.generate` now judges the proposal's pixel
checks instead of refusing the setting.

- `expectrail/jit/run.py`: a pixel stage after the trace checks. Each pixel check's probe is replayed with
  frames (`frame_runner`) on the clean game and the bug build, three times each. The `observer` given to
  the run is asked about every replay, and `pixel.keep` decides. A kept check is judged on the candidate
  the same way, and failing every time is a catch. Observer images are reserved against the change's cap
  before the replays, and the images the observer says it sent are charged. With no observer, no frame
  runner, no bug build, another observer than the check names, or no budget left, a check is `not-run`
  with the reason. An observer that fails or answers badly drops the checks on that probe. A failed
  replay still ends the run as nothing generated (rule 3). `from_base_alone` adds `pixelReproducing` and
  `pixelFromBaseAlone` for records that have pixel rows.
- `expectrail/jit/pixel.py`: the observer protocol (`observe`, which checks the answer as untrusted data),
  `record_row`, and `kept_rows`, which decides keeping from a row's runs and setting, never its status.
- Contract, in one change: `contracts/jit-run.v1.schema.json` gains `pixelChecks` and the pixel setting in
  `settings.offer`. The example is `contracts/examples/jit-run-pixel.json`, written by a test run. The
  writer is `run.generate`, the readers are `pixel.kept_rows`, `run.from_base_alone` and `cli.render`.
- `expectrail/jit/offer.py`: `REPLAYABLE` now includes the pixel setting. A new `REVISABLE`/`revisable`
  keeps `revise` refusing it, because a revision does not carry pixel checks. `OFFERS` is unchanged, so
  the command line's `run`, the workflow and the reproduction score still do not name it.
- `docs/jit.md`: a section on how the replay judges pixel checks.

## What was run
- `python3 -m unittest tests.test_jit_pixel_replay` and the other jit, contract and score tests: OK.
- Full suite on the branch (main a5b7d95 plus this change): `python3 -m unittest discover -s tests -t .`, 3,325 tests, OK, 31 skipped. A first full run found one failure (`tests.test_repro_reach`: the word "reach-" in a docstring of `run.py`, which only `offer.py` may name); the docstring was reworded and the second full run passed.
- Nothing was dispatched. No model and no observer was called. The tests use SAM's recorded answers on
  the bundled game's smoke route (run 43337979278), stamped with the replayed probe's name by a test
  double. They test the plumbing and the rules, not SAM on bench probes.

## Not done
- No SAM observer is wired into a run, the command line or `jit.yml`.
- The reproduction score does not count pixel rows.
- `revise` does not carry pixel checks.
- No reproduction rate has been measured with pixel checks. That needs a live run (SAM on the public
  bench's screen-only defects), which only Sean can dispatch.

## Files
- `expectrail/jit/run.py`, `expectrail/jit/pixel.py`, `expectrail/jit/offer.py`, `expectrail/jit/intent.py`,
  `expectrail/jit/cli.py`
- `contracts/jit-run.v1.schema.json`, `contracts/examples/jit-run-pixel.json`
- `tests/test_jit_pixel_replay.py` (new), `tests/test_jit_pixel_offer.py`, `tests/test_jit_offer.py`
- `docs/jit.md`, `docs/new-work/2026-11-14-pixel-replay.md`
