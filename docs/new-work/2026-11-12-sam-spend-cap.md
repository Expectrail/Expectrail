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
- `agents/judge_ladder.py`: `budget` joins the kinds that waiting does not fix, so the ladder does
  not wait and ask again.
- `docs/sam.md` says so under "Run it".

## What was run
- `python3 -m unittest tests.test_sam`: 73 tests, OK. The 8 new ones use a stand-in sender; with the
  real sender and no cap, a test holds that no connection is opened.
- `python3 -m unittest discover -s tests -t .` on Python 3.13: 2,223 tests, OK, 26 skipped.
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
