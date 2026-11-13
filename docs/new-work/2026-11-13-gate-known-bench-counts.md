# The gate on the known-bugs bench, before and after the repair rule: the counts (#284)

## What changed
#284's "Done when" asks for the gate's decisions on the known-bugs bench (`bench/jit/known/`) before
and after the rule that a declared fix is accepted only when a check demonstrates the repair.

- `python3 -m expectrail.gate.known_bench run` runs the CI gate on each of the bench's eight cases
  (four reported bugs, each with a comment-only wrong fix and the exact-undo correct fix) the way
  blind set 3's arm A did: the bug build as the base, the bug build plus the candidate as the head,
  the gate's own routes (`harness/routes/smoke.json`, `combat.json`) and approved specs, the engine's
  record only. It runs the gate twice per case, with intent `none` and with intent `fix`, and keeps
  both decisions side by side. No model, no generated check.
- New record `expectrail.gate-known-bench/v1`: schema (`contracts/gate-known-bench.v1.schema.json`),
  example (`contracts/examples/gate-known-bench.json`), writer and reader in the same module. The
  reader recomputes the totals from the rows and refuses a record where a declared fix is accepted
  without a demonstrated repair, or where intent `none` was not also an accept, or where an
  unverified fix does not lead with `repair-not-demonstrated`. `show` checks the stored record, says
  when it no longer matches the cases, patches, routes or specs, and prints the page.
- The measurement is stored in `bench/jit/known/gate.json` and rendered in `bench/jit/known/gate.md`;
  `docs/ci-gate.md` points to it. No file the bench's registration pins was changed.

## What was run
- The real engine (Godot 4.7.2, this cloud container, no model, two jobs, 10 min 8 s):
  `python3 -m expectrail.gate.known_bench run --jobs 2`. Result:
  - no stated intent: 4 of 4 wrong fixes accept, 4 of 4 correct fixes accept;
  - declared a fix: 4 of 4 wrong fixes needs-review, 4 of 4 correct fixes needs-review, each with
    first reason `repair-not-demonstrated: ... none of the 2 checks that ran failed before the change`.
  - The one approved spec (`player-stays-above-ground`, on 2 routes) passed on every bug build, so
    no check reproduced any of the four bugs.
- `python3 -m unittest tests.test_gate_known_bench`: 18 tests, OK. They include the rule's effect with
  the gate's own `decide` behind a stand-in replay (nothing reproduces: all needs-review; a check
  failing on the bug: the undo accepts and the comment rejects; a flaky base: needs-review).
- The full suite: in the pull request's description.

## Not done
- The rule's price is in the numbers: with only the approved checks, the four correct fixes also go
  from accept to needs-review. They can be accepted as fixes only once a check that reproduces their
  bug exists (a person's approved check, or a generated check allowed to count under #271).
- Not run: the same bench with generated checks feeding the rule (#271), or in CI.
- `expectrail verify --intent` (the orchestrator, #250, builder one's lane).

## Files
- `expectrail/gate/known_bench.py`
- `contracts/gate-known-bench.v1.schema.json`
- `contracts/examples/gate-known-bench.json`
- `bench/jit/known/gate.json`
- `bench/jit/known/gate.md`
- `tests/test_gate_known_bench.py`
- `docs/ci-gate.md`
- `docs/new-work/2026-11-13-gate-known-bench-counts.md`
