# The public counting audit re-run with the do-nothing, harmless and metamorphic controls (#675)

## What changed

- `expectrail/jit/counting.py`: `public-bench` takes `--do-nothing-rows` (the `rows.json` of
  `tools/do_nothing_public.py`). For each public defect, the page now says:
  - how many of the legacy-kept checks and catches the do-nothing control drops;
  - how many it keeps, and of those, how many fail the control, are indeterminate or were not run.

  A row is used only when it names its record (`sourceRun`) and its check (`specSha256`) by digest.
  Otherwise the check is "cannot tell", neither kept nor dropped. The audit refuses a duplicate row, an
  unknown outcome and a row for a check the records do not have.
- The page also reports the records' metamorphic rows, which are advisory and never assessed for counting.
- `public_custom_route` is factored out of the harmless control, unchanged.
- `tools/do_nothing_public.py`:
  - each row carries `specSha256` and `sourceRun`;
  - a model-proposed probe's route is used when it is supplied in `jit-routes` beside its record with the
    digest the record names (as the harmless control already did).
- `docs/jit.md` and `docs/measurements/675-public-counting-rerun.md` publish the re-run: 0 of 137 counting,
  unchanged. 41 of the 91 legacy-kept checks pass the do-nothing control and 50 stay; of those 50, 24 fail
  it. 0 false rejections on the harmless edit (124 pass, 2 indeterminate, 11 not run). 0 metamorphic rows.

Advisory: the counting classification and the rules are unchanged.

## What was run

- `python3 -m unittest tests.test_jit_counting_rerun`: 7 tests, OK. Before the change: 13 errors.
- `tests.test_jit_counting_rerun`, `tests.test_jit_do_nothing` and `tests.test_jit_harmless_control`
  together: 30 tests, OK.
- Locally, on Godot 4.7.2:
  - `python3 tools/do_nothing_public.py`: 132 replays. The counts were the same as the November measurement.
  - The audit with `--harmless-work` and `--do-nothing-rows`, twice. Both runs gave the same harmless rows.
  - The replays were not sandboxed (no bubblewrap here).
- Full suite on main `da633d5` plus this change: see the pull request.
- No model was called, nothing was dispatched and nothing was spent.

## Not done

- 11 checks were not run on either control. They use model-proposed routes that are only in run
  43465090517's artifacts, and this session's network could not reach the artifact host.
- Counting stays 0 until there is a fresh candidate-withheld run under a trusted producer. That run is
  live, so it is Sean's to dispatch.

## Files

- `expectrail/jit/counting.py`
- `tools/do_nothing_public.py`
- `tests/test_jit_counting_rerun.py`
- `docs/jit.md`
- `docs/measurements/675-public-counting-rerun.md`
- `docs/new-work/2026-11-20-public-counting-rerun.md`
