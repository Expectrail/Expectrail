# A change declared a fix is accepted only when a check demonstrates the repair (#284)

## What changed
On blind set 3 the gate accepted all 34 candidates, 8 wrong fixes among them, because no check
touched any of the eight defects and "no check failed" was read as "the fix is good". The decision
rule now knows what a change says it is for.

- `expectrail.gate.record.decide` takes an `intent`: `fix`, `change` or `none`. For `fix` an
  accept also needs the repair demonstrated: a check that failed on the base and passes on the
  head, on the same route, three times of three on each side. Without one the decision is
  needs-review and its first reason starts `repair-not-demonstrated:`. A failing check still
  rejects. `change` and `none` are judged exactly as before.
- `expectrail.gate.verify` takes `--intent` (`run_gate(intent=...)`). For a fix, each check that
  failed on the base and passes on the head has its route replayed twice more on each side; a
  check counts only when the base fails and the head passes on all three. So a base that failed
  once and then passed (a flaky check) demonstrates nothing. Routes with no such check are not
  replayed again. An intent that is not one of the three stops the run as needs-review, recorded
  as `fix`.
- The findings record carries `intent` (only when it is not `none`) and, for a fix, a `repair`
  block with every run of every check that claims a repair. The reader recomputes which rows
  count, holds the rows to the checks and the decision to the rows. Schema, example, writer and
  reader are in this change.
- The pull-request comment and the review page lead with "No check reproduced the reported bug, so
  this fix is not verified" and say how to get a check; both have a "Declared as" line.

## What was run
- `python3 -m unittest tests.test_gate_intent`: 34 tests, OK. They hold the issue's cases on the
  gate itself with the gate tests' stand-in replay (fixture traces judged by the real evaluator):
  a fix whose base passes every check is needs-review; a fix with a check failing on the base and
  passing on the head is accept; the same with the check still failing on the head is reject; a
  base that fails once and passes twice does not count; a confirming replay that does not finish
  does not count; `none` and `change` give the decision they gave before for every case tried;
  `fix` never gives an easier decision than `none`.
- `python3 -m unittest tests.test_ci_gate`: 75 tests, OK, none changed.
- The full suite on the branch merged with main: in the pull request.
- Not run: the real engine. The rule is about results, and every test here uses the stand-in
  replay. No run on the known-bugs bench was made.

## Not done
- Nothing reads the intent from a pull request yet. The two actions take no `intent` input, so on
  a pull request the gate still runs with `none`: this change alone turns no accept into
  needs-review in CI. Reading a label or a line in the description, and treating a pull request
  that links a bug issue as a fix, is the next slice. It touches the verify action and workflow.
- The intent is written by the verify job, the untrusted half. The trusted comment job does not
  yet read the declaration itself.
- `expectrail verify` (the orchestrator, #250) has no intent flag, and `agents/review_change.py`
  still makes its own "repair demonstrated" judgement, on one run a side.
- The counts on `bench/jit/known/` before and after, which the issue asks for.
- A generated check cannot demonstrate a repair (#271).
- A check that fails before and passes after for a reason other than the reported bug would count.

## Files
- `expectrail/gate/record.py`, `expectrail/gate/verify.py`, `expectrail/gate/comment.py`, `expectrail/gate/page.py`
- `contracts/findings.schema.json`, `contracts/examples/findings-fix-not-demonstrated.json` (new)
- `tests/test_gate_intent.py` (new)
- `docs/ci-gate.md`, `docs/contracts.md`
