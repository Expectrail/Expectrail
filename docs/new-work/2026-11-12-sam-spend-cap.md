# Every SAM run has a spend cap it cannot pass (#267, for #327)

## What changed
Sean's limit for SAM is $200 in a calendar month and never more. Nothing stopped a run from
spending: SAM calls were counted after the fact and only some benches had a cap of their own. A
monthly limit needs every run to have a worst case, so this is the first part.

- `agents/sam_observations.py`: `EXPECTRAIL_SAM_USD_CAP` is the most one process may spend on SAM.
  Every try is counted at list price before it is sent (a failed try too, since whether one is
  billed is not known). A request that would pass the cap is not sent and raises `SamError` with the
  kind `budget`. A value that is not an amount of 0 or more is an error, never "no cap". The real
  sender refuses to open a connection when no cap is set; a stand-in sender (tests, recorded
  answers) is not held to a cap that was never set.
- `agents/judge_ladder.py`: a `budget` stop ends the ladder. No retry and no Glimmer: the candidate
  stays needs-review for a person, and the report says why. (The first version only skipped the
  retry and went on to Glimmer, which is paid, has no cap here and could accept. The merge guard's
  first review ran it and got an accept "judged by glimmer-engine". Fixed in the same pull request.)
  The question is asked before every step that asks a judge again or asks another one, of every
  attempt so far and not only the first: the second review showed a budget stop arriving on the
  retry still went on to Glimmer.
- `docs/sam.md` says so under "Run it".

## What was run
- `python3 -m unittest tests.test_sam`: 73 tests, OK. The 7 new ones use a stand-in sender; with the
  real sender and no cap, a test holds that no connection is opened.
- `tests.test_judge_ladder`: the ladder run on a budget error with a Glimmer stand-in that would
  accept: SAM is asked once, Glimmer is not woken and not asked, the result is needs-review. The
  same with a passing error beside the budget one, and the same when the budget stop arrives on
  the retry after a first try that failed for another reason (SAM asked twice, Glimmer not asked).
  Two plain outages still reach Glimmer.
- `python3 -m unittest discover -s tests -t .` on Python 3.13: 2245 tests, OK, 26 skipped (merged with main at e2a8d22, after the first review's fix).
- **No live call was made.** Nothing here was run against SAM.

## Not done
- **No workflow sets the cap, so every live SAM call from a workflow now stops with the reason.**
  That is deliberate and it is a change Sean should know before he dispatches anything: each live
  workflow needs a cap as an input, with the month's count (reserve before, used after, refuse
  when the month plus this run's cap would pass $200). That is the next part of #267, and the step
  that reads the month's runs needs a permission only Sean can add.
- The cap is per process. A job that starts several processes gives each the same cap; the month's
  count is what will hold a whole job.
- The count is at list price. It was not compared with a bill.
- Glimmer and Muse calls are not capped here.

## Files
`agents/sam_observations.py`, `agents/judge_ladder.py`, `tests/test_sam.py`, `docs/sam.md`
