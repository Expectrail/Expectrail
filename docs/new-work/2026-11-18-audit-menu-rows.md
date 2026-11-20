# The reproduction audit lists the menu run and no longer says menu evidence cannot be attached (#285)

## What changed
`docs/repro-audit.md` still said, in the proposer row and in the limits of the menu-counter step, that menu
evidence could not be attached as generator probes and that the generator had no trusted way to offer menu
actions. #622 (the `signals-reach-evidence-menu` offer) and #624 (the menu probes' replays record the counter)
changed both. The two places now say what held at the audit and what changed on November 18.

The "Sean's next measurement" section listed three dispatches and not the menu run, the only one that can
reach the two counter defects from the report alone. It now lists it, with its bounds: $48 assessed across 24
defects, at most 48 Muse calls, zero SAM images, a 75-minute measure job per defect ($14.40 of runner time at
the assumed price). The total of all listed dispatches is now $192 of assessed budgets.

A new test, `tests/test_repro_audit_dispatches.py`, reads every `gh workflow run jit.yml` command on the page
and checks it against `jit.yml`'s `workflow_dispatch` inputs: dispatched from main, every `-f` input declared,
every choice one the workflow offers, no input given twice, the budget an amount. It also requires the menu
run with the candidate withheld, and a listed run for every `repro` offer other than baseline and the pixel
setting (whose steps are on #286). So the page cannot again fall behind a new offer or name one the workflow
does not have. Seven tests check the checker on made-up commands.

## What was run
- `python3 -m unittest tests.test_repro_audit_dispatches` on the unchanged page: 3 failures (no menu run, three
  dispatches, the menu offer not listed). After the page change: 11 tests, OK.
- `python3 -m unittest discover -s tests -t .` on main 8868a13 plus the change, without the engine: 5,065 tests,
  OK, 63 skipped.
- Nothing was dispatched and nothing was spent.

## Not done
- The live runs the page lists. They spend money and are Sean's.

## Files
- `docs/repro-audit.md`
- `tests/test_repro_audit_dispatches.py`
- `docs/new-work/2026-11-18-audit-menu-rows.md`
