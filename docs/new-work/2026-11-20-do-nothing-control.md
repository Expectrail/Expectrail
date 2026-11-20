# A generated check that passes when its actor does nothing is dropped (#675, piece 1)

## What changed

- `expectrail/jit/do_nothing.py` (new) makes one do-nothing control per check class from the check's own
  subject: `scope.class`, the profile's selector, the one scene whose root node has that name, and that
  scene's script. A class a script makes at run time (the bullet) is never made: each function that
  instantiates its scene returns at once (`shoot` returns `false`). Any other class (player, enemy) is
  frozen: its per-tick and input callbacks return at once. When a step finds nothing or more than one,
  there is no control and the reason is recorded; nothing is guessed.
- `run.generate` replays the clean game with the control for each check that passed the reference, 3
  times, and drops a check that passes all 3 before the near misses. `assess.do_nothing` gives the outcome
  (`passes`, `fails`, `indeterminate`, `not-run`); `assess.validity` adds the reason. Controls are made
  automatically on the real harness; a run with an injected runner gets none and says so on every row.
  `do_nothing=False` turns them off.
- The revision is told `passed-with-the-actor-doing-nothing` for such a check, instead of a wrong reason.
- Contract `jit-run.v1`: each validity row's `doNothing` and a top-level `doNothing` list (schema,
  regenerated example, writer `run.py`, readers `cli.render` and `intent.feedback`, in this change).
- `tools/do_nothing_public.py` measures the control on the public bench's recorded checks.
- The six counting rules, the gate, approvals and registrations are unchanged.

## What was run

- `python3 -m unittest tests.test_jit_do_nothing`: 16 tests, OK. Includes a pipeline run where
  "eight presses give no more air jumps than two" passes the frozen player and is dropped, while
  "walking right moves the player right" fails it and goes on to the near misses.
- The controls applied to a copy of the bundled game with `harness.run.apply_patches` (in the tests).
- Real engine, Godot 4.7.2: one route clean against the frozen player: the clean player moved from x 90 to
  190; the frozen player stayed at x 90.0, y 636.5 for all 160 rows.
- `python3 tools/do_nothing_public.py` on Godot 4.7.2: 132 headless replays, all completed and stable.
  Of 135 checks recorded as passing the reference: 60 pass the control, 40 fail it, 24 indeterminate,
  11 not run. Of 91 kept by the old rule, 45 pass it. Page: `docs/measurements/675-do-nothing-control.md`.
- `python3 -m expectrail.jit.counting public-bench`: 24 defects, 137 checks, 0 counting (unchanged).
- Full suite on main dcbe614 plus this change, without the engine: 5,568 tests, OK, 74 skipped.
  An earlier attempt with the engine present was stopped by my own 25-minute timeout before it finished;
  it is not a result.
- `python3 -m agents.export_scan --paths error` on the 13 changed files: 0 errors, 0 warnings.

## Not done

- No fresh `repro` run under the new rule (it needs a live model run from main; not dispatched).
- The 11 checks on model-proposed probes were not replayed: their routes are not committed.
- `ingest.py` passes its own runner, so it gets no control.
- The six counting rules do not read `doNothing`. Whether they should is a change to what may count, so it
  is left to Sean.
- Pieces 2 (done in #676) and 3 (metamorphic checks) of #675 are not part of this change.

## Files

- `expectrail/jit/do_nothing.py`, `expectrail/jit/run.py`, `expectrail/jit/assess.py`,
  `expectrail/jit/intent.py`, `expectrail/jit/cli.py`
- `contracts/jit-run.v1.schema.json`, `contracts/examples/jit-run.json`
- `tests/test_jit_do_nothing.py`
- `tools/do_nothing_public.py`, `.gitignore`
- `docs/jit.md`, `docs/measurements/675-do-nothing-control.md`, `docs/new-work/2026-11-20-do-nothing-control.md`
