# A spec or route file the gate cannot use never leaves an accept (#340)

## What changed
The gate's rule is that anything unclear is needs-review and is never read as a pass. A check file
it could not use was not held to that rule. The reader put it in the problems, the problems were
added to the reasons, and the decision came from the counts of the checks that did run. A project
with one approved spec, two good routes and one route that is not JSON was accepted: "all 2 checks
pass", then the problem. The pull request comment shows no reasons on an accept, so there the
problem was not shown at all.

- `expectrail/gate/record.py`, `decide`: a fourth input, the number of problems found reading the
  spec and route files. With any, a result that would be accept is needs-review, and the first
  reason says so. A failing check still rejects.
- The record (`expectrail.findings/v0`) carries the count as `checkProblems`: schema, example,
  writer (`run_gate`, and 0 in the record of a run that could not finish) and reader (`read_record`
  recomputes the decision with it, so an accept with a problem counted is refused as a record that
  contradicts itself). A record written before the field existed has none and reads as 0.
- `docs/ci-gate.md` names it in the decision rule; `docs/contracts.md` describes the field.

Found while answering the merge guard's review of #337, which took it that a problem makes the
result needs-review.

## What was run
- Before, on main (5b2ea66), the gate tests' stand-in replay: a route that is not JSON, a route that
  is not a valid route, a route over the size cap, a second spec that is not a valid spec, each
  beside one approved spec and two good routes: accept, four times.
- After: `tests.test_ci_gate`, eight kinds of broken check file, each with and without a base: all
  16 are needs-review, the record reads back equal, and the comment says needs review with the
  reason. A failing check beside a broken route is still reject. A draft spec is still no problem.
- `python3 -m unittest discover -s tests -t .` on Python 3.13: 2,209 tests, OK, 26 skipped.
- The real sample with Godot 4.7.2 (`python3 -m expectrail.orchestrator sample`): accept, reject,
  accept, each as expected.
- One existing assertion changed: `tests/test_jit_rules.py` pinned `decide`'s inputs to three names;
  it now pins four and holds that the new one can only take an accept away.

## Not done
- A route file that is a link is still left out with no reason and no count. The fix is in the
  function #337 rewrites, so it follows when #337 has merged. #340 stays open for it.
- The count is not held against the reasons: a record can say 2 problems and name 1. The reader
  recomputes the decision from the count, which is what decides.
- The orchestrator's job status carries the gate's decision and reasons unchanged; no field of its
  own was added.
- The new tests use the gate tests' stand-in replay, not the engine.
- This repository's own comment job reads a pull request's record with main's schema. Until this
  merges, main's schema does not know `checkProblems`, so on this pull request alone the comment
  job will call the record unreadable.

## Files
`expectrail/gate/record.py`, `expectrail/gate/verify.py`, `contracts/findings.schema.json`,
`contracts/examples/findings.json`, `tests/test_ci_gate.py`, `tests/test_jit_rules.py`,
`docs/ci-gate.md`, `docs/contracts.md`
