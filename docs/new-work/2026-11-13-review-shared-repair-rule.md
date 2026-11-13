# The review judges a repair by the gate's rule: three runs of three on each side (#284)

## What changed
`agents/review_change.py` (the review of a candidate fix against its failing base) used to call a
repair demonstrated when a requested check failed on the base and passed on the candidate once.
The CI gate, since #355, asks for the same thing three times of three on each side. Two commands
could give two answers about the same fix. Now they use one rule:

- `expectrail.change_evidence.review_status` takes a `repair` block and counts a demonstration with
  `expectrail.gate.record.row_counts`, the function the gate's `decide` uses. Without a block, or
  with runs that do not all hold, the status is `NO REPAIR DEMONSTRATED` and the first reason starts
  `repair-not-demonstrated:`, the gate's name. A `counts` written in a block is never trusted.
- The review replays the public route twice more on each side (a new `repeat` stage, by the same
  `agents.verifier.public_route_checks`) for a requested claim that went from FAIL to PASS, and only
  when the status could otherwise be `REPAIR DEMONSTRATED`. A live review without the private routes
  replays nothing more and stays `INCONCLUSIVE`, as before. A crash while replaying again is
  `INCONCLUSIVE`. A run judged another way (observer, evaluator, route) is recorded as missing.
- The change-evidence record gains a `repair` block of the gate's shape. Contract change in one
  pull request: schema (`contracts/change-evidence.schema.json`, also the `repeat` stage), example
  (`contracts/examples/change-evidence.json`), writer (`agents/review_change.py`) and reader
  (`expectrail.change_evidence.load_record` recomputes the block and refuses one that does not follow
  from the rows). Records written before (no block, the three under `docs/review/`) are read as
  written; the review page says those judged each check once a side.
- The review page shows each claimed repair's runs and whether it counts. `docs/review.md` says all
  of this.

## What was run
- `python3 -m unittest tests.test_review_change tests.test_change_evidence tests.test_review_html
  tests.test_review_loop tests.test_base_arm tests.test_review_repair_rule`: 80 tests, OK.
- The real engine (Godot 4.7.2, this cloud container, no model, SAM off, no private routes), the
  bundled request and `agents/fixtures/fix-collision-mask.patch`, with only the evidence label forced
  to `FRESH LIVE` so the repeat stage runs (there are no private routes here): `REPAIR DEMONSTRATED`,
  repair row `player-stays-above-ground` base fail, fail, fail and head pass, pass, pass, counts;
  stages preflight, base, candidate, compare, repeat, export all completed; 131 seconds.
- The other real-engine runs and the full suite are in the pull request's description.

## Not done
- `expectrail verify` has no `--intent` flag yet: that command is the orchestrator's (#250).
- The counts on `bench/jit/known/` before and after the rule.
- Not run: a GitHub run of the review with the private routes (on main's CI), or with SAM on.

## Files
- `expectrail/change_evidence.py`
- `agents/review_change.py`
- `agents/review_html.py`
- `contracts/change-evidence.schema.json`
- `contracts/examples/change-evidence.json`
- `tests/test_change_evidence.py`
- `tests/test_review_repair_rule.py`
- `docs/review.md`
- `docs/new-work/2026-11-13-review-shared-repair-rule.md`
