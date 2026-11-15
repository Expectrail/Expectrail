# jit.yml can withhold the candidate from the model, and repro-score reads the screen record (#285)

## What changed
`jit.yml` has a new dispatch input, `candidate`: `shown` (the default) or `withheld`.

- `plan` checks it (anything other than `shown` or `withheld` is refused) and hands it to the jobs. The
  known-bugs bench is registered with the candidate shown, so bench mode refuses `withheld`.
- Under `withheld`, `propose`, `replay`, `revise`, `replay-final` and `pixel-judge` pass
  `--withhold-candidate`, so the model is given no byte of the candidate and every replay checks the
  proposal was made that way (#285, step 6; the command-line side was built in #475 and earlier).
- `repro-score` passes `--candidate <setting>`, so it counts only records made with the run's setting,
  and `--screen bench/jit/public/screen.json`, so the screen-only defects get their own rate and a miss the
  engine's record does not show gets `route-never-reaches` or `probe-language` from the scorer (#488).
- Under `shown`, every command line is the one it was before. No job gains a secret, an environment or a
  permission; `measure`, `pixel-ask`, `score` and `rehearsal` do not take the input.

These waited for #465, which rewrote the same jobs and is now on main.

## What was run
- `python3 -m unittest tests.test_jit_candidate_workflow`: 16 tests, OK. Each job's shell step is run
  with bash and a stand-in `python`, under both settings and an unexpected value; the argument lists the
  steps build are parsed by the real `expectrail.jit.cli`, and repro-score's is run for real on an empty
  records folder with the committed screen record. With the workflow change reverted, the same file
  gives 16 failures and 8 errors.
- `python3 -m expectrail.repro score --records <empty> --out <dir> --offer signals-reach-evidence-pixel
  --candidate withheld --screen bench/jit/public/screen.json`: exit 0, 24 defects, all no result, the page
  says "Candidate: **withheld**".
- Full suite on the branch (main 6a0b834 plus the change): see the pull request.
- Not run: the workflow itself, any model or SAM call. Nothing was dispatched and nothing was spent.

## Not done
- The live runs that would use this (`signals-reach`, `signals-reach-evidence`, the pixel setting, and
  now any of them with the candidate withheld) are dispatches that spend money: Sean's to start.

## Files
- `.github/workflows/jit.yml`
- `tests/test_jit_candidate_workflow.py`
- `docs/jit.md`
- `docs/new-work/2026-11-15-candidate-input.md`
