# The baseline reproduction rate, 17 of 24, and the miss breakdown (#285)

## What changed
Sean dispatched the baseline at 16:40 UTC: run 43465090517, `jit.yml` from `main` at 1e60550, mode
`repro`, offer `baseline`. Every job succeeded. This change publishes its result and adds the
breakdown of its misses in the issue's vocabulary (#285, steps 1 and 2).

- **The result, on the bench's page and in `docs/jit.md`.** 17 of 24 reproduced (71%); 16 of the 19
  defects that change the engine's record on a library probe (84%; the issue's target is 70%); 13 of
  the 20 nothing was tuned on; no result 0; 91 kept checks; $2.0492 in all, at most $0.1722 for one
  defect, none over the $2 cap.
- **Where it was read.** The score job's log (the scorer's totals line, quoted verbatim) and the 24
  final replay jobs' logs (each defect's proposed, valid and strong counts and spend). The score file
  is in the run's `repro-score` artifact, and this session could not download it: the artifact
  store's host (`productionresultssa9.blob.core.windows.net`) was refused by its network policy, and
  it was not routed around. So **no score record is committed**, and which defect carries which
  reason is worked out from the counts and the visibility table. Every total agrees with both, and a
  test holds the page to that.
- **Hand findings, `expectrail.repro-hand-reasons/v1`.** Schema
  `contracts/repro-hand-reasons.v1.schema.json`; the committed record
  `bench/jit/public/hand-reasons.json` is the example and is written by hand; reader
  `expectrail.repro.breakdown.load`. It holds the findings of November 12 (already on the bench's
  page, made before any live run) for the five defects no library probe shows. A finding may give
  only `route-never-reaches` or `probe-language`, the two reasons no record separates.
- **`python3 -m expectrail.repro breakdown --score <repro-score.json>`** (`expectrail/repro/breakdown.py`)
  prints the misses by reason. The rule: a hand finding replaces the scorer's reason only where it is
  `undetermined`; it never replaces a reason read from the records and never changes an outcome.
- **The breakdown of the baseline's 7 misses:** `route-never-reaches` 2 (by hand: the two coin
  counter defects, pause menu only), `no-signal` 2 (the camera defects), `probe-language` 2 (by hand:
  the two screen-only defects), `wrong-predicate` 1 (`coin-stays`). Three of the seven are read by
  the signals of #323, which are on offer under `signals-reach`.

Decisions:
- **Publish from the logs rather than wait.** The rate and every per-defect count are printed in the
  logs, and the totals cross-check. Waiting for a session that can reach the artifact store would
  have left the issue's first number unpublished. What could not be read is said on the page.
- **No score record is constructed by hand.** A record built from the logs would carry digests and
  rows nobody scored. The test of the page is a consistency test and says it gives way to a re-score
  once the file is committed.
- **Hand findings cannot move the rate**, and the scorer's reasons stand where they exist, including
  `wrong-predicate` for `coin-stays`, which the page has long said is unfair there. The page notes it
  beside the count instead of changing the count.
- `no-shooting-in-air` was reproduced although no library probe shows it. Its record was not read,
  so how is not said.

Guard: test change intended (#285)
Three tests asserted that the pages say no reproduction rate has been measured. That stopped being
true with run 43465090517. `tests/test_repro_score.py` `NoRateYet` became `BaselineAsPublished`
(the page's table agrees with the quoted totals, the visibility record and the breakdown rule; still
no score file committed); `tests/test_repro_bench.py` and `tests/test_repro_reach.py` now assert their
sections' own "not a rate" sentences.

## What was run
- Run 43465090517 read through the API: conclusion `success`; every job `success` except `rehearsal`
  and `score` (`skipped`, as in this mode). Plan job's log: `MODE: repro`, `OFFER: baseline`.
- The 24 transcribed rows were checked by a script against the 24 logs and `visibility.json` (all
  agree); the sums against the totals line (spend 2.0492, kept 91, reproduced 17, trace-visible 16 of
  19, untuned 13 of 20).
- `python3 -m unittest tests.test_repro_breakdown tests.test_repro_score tests.test_repro_bench tests.test_repro_reach tests.test_schema_pattern`: OK.
- Full suite on the branch merged with current main: see the pull request.

## Not done
- Committing the score file and the 24 records from the `repro-score` artifact, and a test that scores
  them again. It needs a session or a person that can download the artifact (90 days' retention).
- Reading `no-shooting-in-air`'s record to say how it was reproduced.
- The `signals-reach` and `signals-reach-evidence` runs (a person dispatches them).

## Files
- `expectrail/repro/breakdown.py`, `expectrail/repro/__main__.py`
- `contracts/repro-hand-reasons.v1.schema.json`, `bench/jit/public/hand-reasons.json`
- `bench/jit/public/README.md`, `docs/jit.md`, `docs/contracts.md`
- `tests/test_repro_breakdown.py`, `tests/test_repro_score.py`, `tests/test_repro_bench.py`, `tests/test_repro_reach.py`
- `docs/new-work/2026-11-13-reproduction-baseline.md`
