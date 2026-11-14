# Checks from the report and the bug build alone: the model can be given no byte of the fix (#285, step 6)

## What changed
Step 6 of #285 asks that a reproducing check be derivable without the candidate fix, so a fix cannot
shape the check that judges it, and that checks which needed the candidate are marked and never count
under #271. Until now the proposer was always given the candidate patch and the diff map made from it.

- `--withhold-candidate` on `propose`, `revise` and `run` (`expectrail/jit/cli.py`), and
  `candidate_to_model="withheld"` in `run.generate`. Under it the model is given no byte of the candidate:
  the user prompt has no `untrustedCandidatePatch` and no `patchTouches`, every library probe is on offer
  (`diff_map.withheld_map`), and the system prompt's first three paragraphs say no fix is shown and ask
  for checks about the reported behaviour. The rest of the system prompt is unchanged.
- The candidate is still checked to be a patch, replayed and judged as before.
- A withheld proposal is bound to the report (`reportSha256`, `patchSha256: null`, `candidate: withheld`),
  so one proposal can judge any fix of that report. An intent, proposal or first-round record made one way
  is refused by a step made the other way (`CANDIDATE_MISMATCH`, `PROPOSAL_MISMATCH`, `RECORD_MISMATCH`).
- Contract: `settings.candidate` (`shown` | `withheld`) in `contracts/jit-run.v1.schema.json`. A record
  without it was made with the candidate shown. New example `contracts/examples/jit-run.json`, a withheld
  run of the wrong air-jump fix on the simulated game. The writer is `run.generate`. The readers are
  `run.from_base_alone`, the record page (`cli.render`) and `intent.load_record`.
- `run.from_base_alone(record)` lists the checks that passed on the clean game and failed on the bug build
  3 of 3, and of those, the ones proposed with the candidate withheld. That is the first condition of #271.
- Off by default. With the candidate shown, the system prompt is byte for byte as before under every
  offer, and so are the user prompt and the proposal file. Tests hold this, and the existing digest test
  still passes.

## What was run
- `python3 -m unittest tests.test_jit_withheld`: 27 tests, OK. They check that no byte of a marked
  candidate reaches the model, in one step, in two steps and in the revision. Two different fixes give the
  model identical requests; the shown control differs. The wrong fix is still caught. Each mismatch is
  refused. The example is valid and rebuilds from the simulated game. The CLI passes the setting only
  when the flag is given.
- `python3 -m unittest discover -s tests -t .` on the branch (main c5d1e53 plus this change), after the pinned fetch: 3,112 tests, OK, 27 skipped.
- Nothing was dispatched. No model was called and nothing was spent. The new tests use the simulated game; Godot ran only in the suite's existing engine tests.

## Not done
- `jit.yml` has no input for it yet, so no live run can use it. That is the next slice: a `candidate`
  input for the propose, replay and revise jobs, `withheld` for repro mode.
- The reproduction score does not yet count only withheld records, or report the two separately.
- A withheld proposal is bound to the report, not the base patches. The measurements it was given are
  checked against the base patches as before.
- The remaining conditions of #271 (relevance, exercised coverage, provenance in the receipt).

## Files
- `expectrail/jit/intent.py`, `expectrail/jit/run.py`, `expectrail/jit/cli.py`, `expectrail/jit/diff_map.py`
- `contracts/jit-run.v1.schema.json`, `contracts/examples/jit-run.json`
- `tests/test_jit_withheld.py`
- `docs/jit.md`
- `docs/new-work/2026-11-13-candidate-withheld.md`
