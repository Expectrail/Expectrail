# The public baseline's reproduction rate under the do-nothing rule (#285)

## What changed

Since #675 the generator drops a check that passes all three runs of the do-nothing control. The
public baseline (run 43465090517) was scored before that rule, and `docs/repro-audit.md` reported only
its legacy rate, 17/24 (16/19 trace-visible).

- `expectrail/repro/control_rate.py` and `python3 -m expectrail.repro control-rate`: reads a baseline
  score, its records and the control's per-check rows (with the counting audit's reader), binds each row
  by record and check digest, and says per reproduced defect whether a reproducing check fails the
  control, is only indeterminate, was not judged (cannot tell), or every one passed it (dropped). A
  pixel or candidate-withheld score is refused, and a record that is not the file the score names is
  refused.
- `bench/jit/public/do-nothing-rows.json`: the control's rows from `tools/do_nothing_public.py`, run here.
- `docs/repro-audit.md`: a new section with the result, and the 70% target row says the baseline is
  below the target under today's rule.

**Result:** 11/24 reproduced (45.83%); trace-visible 11/19 (57.89%), below the 70% target; untuned
9/20. Five dropped (`air-jump`, `enemy-ledge`, `slow-left`, `slides-after-stop`, `enemy-fast-left`),
one cannot tell (`no-shooting-in-air`, whose check #747 measured as passing the control). Only 7 defects
(7/19 trace-visible) have a reproducing check shown to fail the control; four rest on indeterminate
checks.

## What was run

- `python3 tools/do_nothing_public.py --work <new folder> --out <page>` on Godot
  4.7.2.stable.official.ed1daf0bf, headless, locally: 44 route groups, 132 replays, about 10 minutes.
  Summary printed: 137 checks, 135 on the reference; 56 pass, 35 fail, 33 indeterminate, 11 not run;
  41 of the 91 legacy-kept checks pass. These equal the November 20 measurement. Not sandboxed (no
  bubblewrap here). The four public route archives could not be downloaded (the artifact host is not
  reachable from this machine), so the 11 checks on model-proposed routes were not run.
- `python3 -m expectrail.repro control-rate --score bench/jit/recordings/public-43465090517/repro-score/repro-score.json --records bench/jit/recordings/public-43465090517/repro --do-nothing-rows bench/jit/public/do-nothing-rows.json`:
  the totals above.
- `python3 -m unittest tests.test_repro_control_rate`: 15 tests, OK. The full suite result is in the pull
  request.
- No model was called, no SAM request was made and nothing was dispatched.

## Not done

- No new generation: this applies today's keep rule to the frozen checks. A live run under the current
  generator, candidate withheld, is still Sean's dispatch (listed in `docs/repro-audit.md`).
- The 11 model-route checks were not run here; their results are from #747's page, cited, not recomputed.

## Files

- `expectrail/repro/control_rate.py`, `expectrail/repro/__main__.py`
- `tests/test_repro_control_rate.py`
- `bench/jit/public/do-nothing-rows.json`
- `docs/repro-audit.md`
- `docs/new-work/2026-11-21-repro-do-nothing-rate.md`
