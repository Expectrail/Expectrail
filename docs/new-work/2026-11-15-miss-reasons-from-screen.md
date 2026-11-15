# The scorer gives `route-never-reaches` and `probe-language` itself when it has the screen record (#285, step 2)

## What changed
Step 2 of #285 asks for every miss to be diagnosed in a fixed vocabulary. Until now the scorer could not
tell two of its reasons apart: a miss the engine's record shows on no library probe was `undetermined`,
and only a hand finding (`bench/jit/public/hand-reasons.json`) could call it `route-never-reaches` or
`probe-language`. The screen record (`bench/jit/public/screen.json`, `expectrail/repro/screen.py`)
already measures what each defect changes in the frames as well as the record, so the scorer can use it.

- `score.screen_reason(visibility, sees, pixel_offer)`: for a row whose visibility is `none`,
  `neither` gives `route-never-reaches` and `screen-only` gives `probe-language`, except under the pixel
  setting, where checks about the screen were on offer and the miss stays `undetermined`.
- The scorer applies it only after the reasons read from the run (`budget`, `flaky`) and from the
  visibility record (`wrong-predicate`, `no-signal`). A screen record that says the engine's record
  differs where the visibility record says it does not leaves the miss `undetermined`, and the
  evidence says the two measurements disagree.
- The reader (`score.problems`) recomputes both reasons from the row's `visibility`, `screen` and the
  score's offer. It refuses either one where the screen record does not show it, and it refuses
  `undetermined` where the screen record gives a reason. Without a screen record, both stay refused, as before.
- Contract: the schema's `reason` description says when the two are given (the enum is unchanged). New
  example `contracts/examples/repro-score-screen.json`. The writer is `score.score(..., screen_path=...)`
  and the readers are `score.problems` and `breakdown.breakdown`. A hand finding for a miss the scorer
  now classifies is shown beside it and counts for nothing, by the breakdown's existing rule.
- `docs/jit.md` and the docstrings of `score.py` and `breakdown.py` say how it works.

## What was run
- `python3 -m unittest tests.test_repro_score_screen_reasons`: 22 tests, OK. They cover each reason,
  that the run's reasons and the visibility record come first, disagreeing measurements, the pixel
  setting, a screen record missing a defect, five hand edits the reader refuses, the example, and the
  breakdown. One test reads the committed records: for each of the baseline's four misses that the
  records could not classify (run 43465090517, as transcribed on the bench's page), the rule gives the
  reason that defect's November 12 hand finding gives: `route-never-reaches` for the two coin-counter
  defects, `probe-language` for `enemy-walks-backwards` and `bullet-behind-scenery`.
- Mutation check: with the reader's recompute disabled, 3 of those tests fail.
- `python3 -m unittest discover -s tests -t .` on the branch (main 8581a0f plus this change), after the
  pinned fetch: 3,655 tests, OK, 42 skipped.
- Nothing was dispatched. No model, observer or engine was used, and nothing was spent.

## Not done
- No score file made this way from a live run's records: none is committed. The baseline's
  `repro-score` artifact (run 43465090517) is still not attached.
- The bench's page still shows the baseline breakdown with its hand findings, as transcribed. It is
  unchanged because the counts are the same, and the page quotes that run as it was scored.
- The `candidate` input in `jit.yml` still waits on #465.

## Files
- `expectrail/repro/score.py`, `expectrail/repro/breakdown.py`
- `contracts/repro-score.v1.schema.json`, `contracts/examples/repro-score-screen.json`
- `tests/test_repro_score_screen_reasons.py`
- `docs/jit.md`
- `docs/new-work/2026-11-15-miss-reasons-from-screen.md`
