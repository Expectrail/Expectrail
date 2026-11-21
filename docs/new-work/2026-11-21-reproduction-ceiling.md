# The reproduction ceiling by hand: two defects need a better generator, one needs a compound check (#762)

## What changed
- Hand-written reproduction checks for `slow-left`, `slides-after-stop` and `air-jump`, in the generator's
  planner format, under `bench/jit/ceiling/<defect>/round1.json`. Each was written from the report, the
  profile, the probe library and the clean game's measurements. They were committed (0c28a52) before any
  replay of a defect build. No `defect.patch`, no `bugs/reported/air-jump.patch` and no recorded or
  stand-in proposal was opened.
- `tools/reproduction_ceiling.py` turns each answer into a proposal with the generator's own parser and
  offer (`signals-reach-evidence-menu-control`, candidate withheld). It then replays each check 3 times on
  four builds: the clean game, the defect, the do-nothing control and the comment-only edit. It judges
  each run with `run._evaluate` and `do_nothing.judge`, and records the clearance, the defect margin and,
  for two checks, the two judged together.
- `bench/jit/ceiling/rows.json`, the proposals, and the generator job's own records for each proposal.
- `docs/measurements/762-reproduction-ceiling.md`: per defect, the obligation, the check, the round, the
  four results, the clearance and which limit binds.
- `tests/test_reproduction_ceiling.py` (15 tests). The clearance agrees with the evaluator's comparators.
  The keep and compound rules hold. Every answer passes the generator's parser. The rows match the
  committed answers, reports and patches. The published table equals the rows.

Nothing in the generator, its prompts, the schema or `expectrail/jit/intent.py` changed.

## What was run
- `python3 tools/reproduction_ceiling.py --work … --rows bench/jit/ceiling/rows.json` on Godot 4.7.2,
  twice. Both runs gave the same table, and every route's three traces were identical (28 groups).
  - `slow-left`: kept.
  - `slides-after-stop`: kept.
  - `air-jump`: neither check is kept alone; the pair judged together passes all four.
  - Bubblewrap is not installed here, so the replays ran without isolation.
- `python -m expectrail.jit.cli run --withhold-candidate --offer signals-reach-evidence-menu-control` on each
  proposal, with the defect as base and `no-fix.patch` as candidate. Results: `slow-left` 1 valid, 1 strong
  catch; `slides-after-stop` 1 valid, 1 strong catch; `air-jump` 0 valid of 2.
- Full suite on this branch merged with current main: see the pull request.
- No model was called. Nothing was dispatched or spent.

## Not done
- No revision round was used. For `air-jump` the measurement argues that no single check in the language
  can survive the control, so a revision cannot help.
- `enemy-ledge` was left out, as the issue asks.
- The compound check is a schema change, filed as its own issue, not built here.
- Three defects are not a rate.

## Files
- `bench/jit/ceiling/` (round answers, proposals, pipeline records, `rows.json`)
- `tools/reproduction_ceiling.py`
- `tests/test_reproduction_ceiling.py`
- `docs/measurements/762-reproduction-ceiling.md`
- `docs/new-work/2026-11-21-reproduction-ceiling.md`
- `.gitignore` (lets `tools/reproduction_ceiling.py` be tracked)
