# Read survival under the do-nothing control from a live run's own records (#285)

## What changed
`docs/repro-audit.md` states, before the control run, that the control setting is read against the menu
setting on survival under the do-nothing control, valid catches and the form histogram, and that a reader
of a live run's own do-nothing rows (`validity[].doNothing`) was still to be built. This builds it.

`python3 -m expectrail.repro control-survival --run <score> <records> [--run ...] [--out page.md]` reads
each run's score and records and puts every proposed check in one class: `passes`, `fails`,
`indeterminate`, `not-run` (passed the clean game, no control given), `off-reference` (failed the clean
game, so the control was not run), `no-row` (no validity row) or `absent` (the record predates the
control). It reports survival as the audit stated it (share of proposed checks not `passes`) and among
the checks the control judged, the score's valid catches, and the proposed checks by operation and by the
forms of `expectrail/repro/control_form.py`. Several runs go side by side on one page.

It fails closed on a record that disagrees with itself: an outcome its own runs do not give, a check kept
valid after passing the control, a control run for a check that failed the clean game, an unknown outcome,
a validity row for a check not proposed or given twice, a reproducing check that passed the control or
has no validity row, a record that is not the file the score names, a record of another setting than the
score's, or some records with rows and some without. With any record `absent`, survival is "cannot tell".

The audit's bullet that said the reader was not built now names the command, the two survival shares and
the baseline's reading (137 checks, all `absent`; survival cannot be told), kept equal to the reader by a
test.

## What was run
- `python3 -m unittest tests.test_repro_control_survival tests.test_repro_control_form tests.test_repro_control_rate`:
  OK.
- `python3 -m expectrail.repro control-survival --run bench/jit/recordings/public-43465090517/repro-score/repro-score.json bench/jit/recordings/public-43465090517/repro`:
  137 proposed, all `absent`, survival `null` (cannot tell), catches 91 checks and 17 of 24 defects.
- Full suite on this branch merged with current main: see the pull request.

No model, no engine, no dispatch; nothing was spent.

## Not done
- Not run on a live record with do-nothing rows: none exists yet. The menu and control runs (`jit.yml`
  from main, `mode=repro`, `candidate=withheld`, `budget_usd=2`, at most $48 assessed each) are Sean's
  to dispatch. The live-run cases in the tests are the baseline records with rows added in the writer's
  shape.
- Pixel checks of a pixel setting are not read.

## Files
- `expectrail/repro/control_survival.py` (new)
- `expectrail/repro/__main__.py`
- `tests/test_repro_control_survival.py` (new)
- `docs/repro-audit.md`
- `docs/new-work/2026-11-21-control-survival.md` (new)
