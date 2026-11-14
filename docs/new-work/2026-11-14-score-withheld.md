# The reproduction score counts records made with the candidate withheld apart (#285)

## What changed
Issue #285, step 6, the score half. A run can already withhold the candidate from the model
(`--withhold-candidate`, #414), and each record says `settings.candidate`. The reproduction score now
counts one candidate setting at a time, the way it counts one offer at a time:

- `python -m expectrail.repro score --candidate withheld` counts only records made with the candidate
  withheld. The default, `shown`, counts only records made with it shown, including records written
  before the setting existed. A record of the other setting is a row with no result, with that reason.
- A withheld score says `"candidate": "withheld"` on its record and, on its page, that every
  reproducing check was derived from the report and the bug build alone (#271's first condition). A
  shown score leaves the field out, so a score made as before is byte for byte what it was.
- Contract: `contracts/repro-score.v1.schema.json` gains `candidate` (`const: "withheld"`, optional);
  new example `contracts/examples/repro-score-withheld.json`; writer and reader in
  `expectrail/repro/score.py`; the command in `expectrail/repro/__main__.py`.

No change to `jit.yml`: #465 (labelled `needs-sean`) rewrites the same jobs, and a second change there
would leave it a conflict.

## What was run
- `python3 -m unittest tests.test_repro_score_withheld`: 13 tests, OK. Among them, the pipeline on the
  simulated game with a fake model and the candidate withheld, scored by the command: the air-jump
  defect is reproduced under `--candidate withheld`, the scorer's reproducing checks equal
  `run.from_base_alone(record)["fromBaseAlone"]`, and the same record is no result by default.
- With the new check in `_read` disabled by hand, 6 of the 13 tests fail (then restored).
- Full suite on the branch merged with main: see the pull request.
- No engine, no model, no dispatch. Nothing was spent.

## Not done
- A `candidate` input in `jit.yml` (repro mode passing `--withhold-candidate` to propose, revise and
  the replays, and `--candidate withheld` to `repro-score`). Waits until #465 is decided.
- A live run with the candidate withheld. It needs that input, then a dispatch by Sean.

## Files
- `expectrail/repro/score.py`
- `expectrail/repro/__main__.py`
- `contracts/repro-score.v1.schema.json`
- `contracts/examples/repro-score-withheld.json`
- `tests/test_repro_score_withheld.py`
- `docs/jit.md`
- `docs/new-work/2026-11-14-score-withheld.md`
