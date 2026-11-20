# The generator offers mirror-inputs metamorphic checks, judged by the same rule, as advisory rows (#675)

## What changed
- `jit run --metamorphic` (`run.generate(..., metamorphic=True)`) offers mirror-inputs metamorphic checks
  after the proposed checks are judged. `metamorphic.offer` picks at most 4 pairs (16 checks): the probes the
  proposed checks use first, then library order, one pair of each twin; one diagnostic line says what was
  skipped.
- Each check is judged by the same rule as a proposed check, on its own `metamorphic-*` replays: clean 3 of 3,
  the do-nothing control (a check passing it is dropped), the near misses including the bug build (a near miss
  that gives the candidate's trace is no kill), then the candidate.
- The rows are the record's new `metamorphic` field, with `settings.metamorphic`. They are never in
  `proposed`, `validity`, `catches`, `counts`, the gate summary or the counting audit. Running out of budget or
  a replay error in this stage leaves the proposed checks' results and says why on each unfinished row.
- Contract `jit-run.v1`: schema, a new example `contracts/examples/jit-run-metamorphic.json`, writer
  (`run.py`) and readers (`cli.render`, tests) together.
- A hand-written stand-in, two candidates and their recorded runs for `slow-left`, in
  `bench/jit/stand-in/slow-left-metamorphic-comment-only/` and `.../slow-left-metamorphic-revert/`.

## What was run
- `python3 -m unittest tests.test_jit_metamorphic_generate`: 15 tests, OK.
- Real engine, Godot 4.7.2, no model (`docs/measurements/675-metamorphic-generate.md`): on `slow-left` with
  the candidate withheld, 4 of 16 offered checks are valid; they catch the comment-only candidate 4 of 4 and
  pass the revert 4 of 4. 94 replays per run, $0.17 assumed.
- Full suite: see the pull request.

## Not done
- `jit.yml` does not pass `--metamorphic`; no live run was made.
- Slice 3: one outside game.
- The counting audit re-run (`Done when`, last item) after a fresh run.

## Files
- `expectrail/jit/run.py`, `expectrail/jit/metamorphic.py`, `expectrail/jit/cli.py`
- `contracts/jit-run.v1.schema.json`, `contracts/examples/jit-run-metamorphic.json`
- `tests/test_jit_metamorphic_generate.py`
- `bench/jit/stand-in/slow-left-metamorphic-comment-only/`, `bench/jit/stand-in/slow-left-metamorphic-revert/`
- `docs/jit.md`, `docs/measurements/675-metamorphic-generate.md`, this file
