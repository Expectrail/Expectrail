# A fix whose check failed before the change but was not decided after it says so (#560)

## What changed
For a change declared as a fix, the gate said "none of the N checks that ran failed before the change,
so no check reproduced the reported bug" whenever no repair row existed. A row exists only for a check
that failed before and passed after. So when the check failed on the base and needed review on the head
(the nightly tester's run with no vision key), the words contradicted the record, which holds the base
failure.

- `expectrail/gate/record.py`: `undecided_after_failure(checks)` counts checks that failed on the base
  and are needs-review or replay-error on the head. `decide(..., undecided_after_failure=N)` uses it only
  to word the `repair-not-demonstrated` reason: "N check(s) failed before the change but could not be
  decided after the change (needs review, or the replay did not finish), so nothing shows the bug is
  fixed". The decision is unchanged in every case (a test holds this). The record reader passes the same
  count. `unverified_fix_headline(doc)` picks the headline from a record's checks, or, for a job status
  that carries only reasons, from the repair reason's words.
- `expectrail/gate/verify.py` passes the count. `comment.py` and `page.py` lead with "A check failed
  before the change, but its result after the change could not be decided, so this fix is not verified"
  in that case. `expectrail verify`'s text output (`orchestrator/cli.py describe`) uses the same headline.
  Every other case keeps its old words.
- `docs/ci-gate.md` describes the case.

## What was run
- `python3 -m unittest tests.test_fix_undecided_after tests.test_gate_intent tests.test_verify_intent
  tests.test_gate_intent_from_pr tests.test_two_observers`: 133 tests, OK.
- Three mutations (the count not passed by the gate, the comment's branch removed, replay-error not
  counted): each made 2 of the 9 new tests fail.
- `python3 -m unittest discover -s tests -t .` on the branch (current with main at ba050a7): 4,556 tests, OK, 52 skipped.
- No Godot and no model ran: the new tests use the stand-in replays and the stand-in vision of
  `tests/test_ci_gate.py` and `tests/test_two_observers.py`.

## Not done
- Not re-run as the tester ran it (`expectrail verify --auto-fix` on the real game with no key).

## Files
- `expectrail/gate/record.py`, `expectrail/gate/verify.py`, `expectrail/gate/comment.py`,
  `expectrail/gate/page.py`, `expectrail/orchestrator/cli.py`, `expectrail/orchestrator/request.py`
- `tests/test_fix_undecided_after.py`
- `docs/ci-gate.md`, `docs/new-work/2026-11-16-fix-undecided-after.md`
