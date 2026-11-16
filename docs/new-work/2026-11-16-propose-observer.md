# The propose step is told which observer will judge, so the proposer can be offered the sensor (#286)

## What changed
A run's pixel checks are judged by one observer, and a check naming another is not run. Until now the
propose step was not told which observer would judge, so the proposer was offered SAM only, and no
proposal could name the no-model template sensor (`visual-sensor`, #262) that #543 made an observer.

- `expectrail/jit/pixel.py`: `proposed(observer)` gives the one observer a proposal may name (SAM by
  default, or `visual-sensor`); `PROPOSED` and `NOT_PROPOSED` are replaced by `PROPOSABLE`,
  `DEFAULT_OBSERVER`, `check_observer` and `not_proposed`. A check naming another observer is refused
  with a reason that names the one judging the run.
- `expectrail/jit/intent.py`: `prompt`, `spark_intent`, `parse_answer_pixel`, `propose_to_file`,
  `from_proposal` and `revise_to_file` take `observer`. The prompt's `pixelChecksOffered` names only that
  observer; the system prompt does not change. The proposal records `"observer"` only when it is not SAM,
  so a proposal for SAM is byte for byte as before (a test compares the bytes and the request bodies).
  `from_proposal` refuses a proposal made for another observer (`PROPOSAL_MISMATCH`), an observer it does
  not know or one stated under a setting with no pixel checks (`PROPOSAL_INVALID`), and a saved pixel check
  naming another observer than the one stated. `observer=None` is a run that judges no pixel checks: it
  reads a proposal for any observer, as jit.yml's first replay does, and the pixel rows are `not-run`.
- `expectrail/jit/run.py`: the intent call's reservation prices the prompt for the intent's observer; an
  intent with an observer that cannot be used under the run's setting generates nothing
  (`OBSERVER_INVALID`). A check naming another observer than the run's is still `not-run`, as before.
- `expectrail/jit/cli.py`: `propose --observer` and `revise --observer` (`sam-3.1-anchor` by default, or
  `visual-sensor`; the pixel setting only, otherwise exit 2). `run --observer visual-sensor --sensor-bank
  BANK` builds the sensor, with its frame plan from `--sam-every` and `--sam-first`; it refuses SAM's
  answer, live, run, box, pad and lift arguments and the capture and replay jobs. `run --proposal` passes
  its observer to `from_proposal` (`--observer none` passes None).
- `docs/jit.md`, the docstrings of `pixel.py` and `template_observer.py`: what is offered now.

No schema changed: the proposal (`expectrail.jit-proposal/v0`) has no contract file, and the run record is
as it was.

## What was run
- `python3 -m unittest tests.test_jit_propose_observer`: 21 tests, OK. On recorded model replies (no
  call) and synthetic frames: the menu and the refusals per observer; the prompt for SAM unchanged and for
  the sensor offering the player only; propose, save and replay, with every mismatch and edit refused; the
  revision keeps the observer and refuses another; the command line builds the sensor and refuses every
  wrong combination; and end to end, a check proposed for the sensor, saved, replayed and judged by the
  sensor on the simulated game is kept (3 of 3 each way), catches a wrong fix and not a good one, with 0
  SAM images.
- `python3 -m unittest discover -s tests -t . -p "test_jit*.py"` before the new file: 446 tests, OK.
- The full suite after the pinned fetch: see the pull request.
- No engine, no model, no SAM call, no dispatch. Nothing was spent.

## Not done
- jit.yml does not pass `--observer visual-sensor` or a bank to any job.
- No bank has been calibrated on the bundled game's clean frames, so the screen-only bench defects have
  not been judged with the sensor.
- The sensor still knows the player only (enemy and bullet need their own templates and prediction maps).

## Files
- `expectrail/jit/pixel.py`, `expectrail/jit/intent.py`, `expectrail/jit/run.py`, `expectrail/jit/cli.py`,
  `expectrail/jit/template_observer.py`
- `docs/jit.md`
- `tests/test_jit_propose_observer.py` (new)
- `docs/new-work/2026-11-16-propose-observer.md` (this file)
