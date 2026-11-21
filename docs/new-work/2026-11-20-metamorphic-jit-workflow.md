# The mirror metamorphic checks turned on in jit.yml (#675)

## What changed

- `.github/workflows/jit.yml`: every rehearsal case runs `jit run --metamorphic`, and its check runs
  `tools.jit_rehearsal_check --metamorphic`. A dispatch takes a new boolean input `metamorphic`, off by
  default. The plan job checks that it is `true` or `false`, refuses it in bench mode (the known-bugs bench is
  registered without it), and passes it on. When it is on, the replay, replay-final and pixel-judge jobs all
  pass `--metamorphic`. So whichever of them writes the kept record, that record has the rows; replay-final
  copies round 1's record when nothing was revised. No secret, no `environment:`, no trigger and no permission
  changed. The checks need no model, so this adds replays and no spend.
- `tools/jit_rehearsal_check.py`: `--metamorphic` makes it fail when the record was not made with the setting,
  has no metamorphic row, or lists a metamorphic check among the counted checks or the catches. Those rows are
  advisory. What the rows say is not asserted: neither rehearsal defect depends on direction.
- `docs/jit.md`: the metamorphic section says how `jit.yml` uses the setting. It no longer says `jit.yml`
  does not pass it.

Advisory: nothing here changes what may count or clear a change.

## What was run

- `python3 -m unittest tests.test_jit_metamorphic_workflow tests.test_jit_rehearsal_check`: 37 tests, OK.
  The new workflow tests run each step's shell with a stand-in `python` and read the flag it passed.
- All three rehearsal cases with the workflow's own command plus `--metamorphic`, on Godot 4.7.2 here, then
  `python3 -m tools.jit_rehearsal_check --metamorphic` on each record. Each run completed, and the check passed on each:

  | Case | Seconds | Counts | Metamorphic rows | Valid among them |
  | --- | --- | --- | --- | --- |
  | air-jump-undo | 633 | 3 proposed, 1 valid, 0 catches | 16 | 0 |
  | air-jump-comment-only | 265 | 3 proposed, 0 valid, 0 catches | 16 | 0 |
  | gun-cooldown-long-comment-only | 582 (while the full suite also ran) | 6 proposed, 6 valid, 6 strong | 16 | 0 |

  The CI rehearsal took 2 to 4 minutes per case before this change (run 44768784886). The job's limit is 40
  minutes.
- Full suite on main 8d503f2 merged with this change, with the engine present: 5,833 tests, OK, 44 skipped.

## Not done

- No dispatch and no live run. The CI rehearsal on this pull request is the first run in CI.
- Re-running the public counting audit (the last item of #675's `Done when`).

## Files

- `.github/workflows/jit.yml`
- `tools/jit_rehearsal_check.py`
- `tests/test_jit_metamorphic_workflow.py` (new)
- `tests/test_jit_rehearsal_check.py`
- `docs/jit.md`
- `docs/new-work/2026-11-20-metamorphic-jit-workflow.md` (new)
