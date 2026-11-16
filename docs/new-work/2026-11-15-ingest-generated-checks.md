# Advisory generation for uncovered playtest reports (#531, round two)

## What changed

Applied the round-one ingest handover onto main a98dcb08c2d7fe068283e97148b07a37d423d91e
in a separate local worktree. Its public CLI registration needed a context-only
adaptation after main's CLI additions; behavior is unchanged. A local foundation
commit records that dependency, with no push or GitHub write.

Added `ingest --propose`, explicit trusted clean/profile options, and a saved
stand-in response option. The existing JIT generator receives the bug via its
untrusted bug-report path, the exact submitted input route as a trusted-named
probe, and captured clean/base builds via its runner interface. The existing
candidate-withheld mode and `from_base_alone` keep reader alone decide whether
the generated check reproduces. Generated checks remain advisory and never
accept, reject, become approved or start a fixer.

Added a closed reproduction record, schema, examples, writer and reader. Job
statuses and evidence name approved / generated-advisory / none. Snapshot inputs
are captured and bound into request digests. Unknown report text cannot pick
references, providers or checks. A stand-in response has no live fallback. Without one, the existing explicit
spec-role cap is required before the existing Spark transport can be constructed;
that branch was tested with a patched cap and stand-in transport, never live.
The minimal wheel can still import ordinary verification; the optional repository
JIT worker runs only on explicit proposal and reports unavailable if absent.
See docs/playtest-propose.md for usage, trust boundaries, measured demonstration
and the unexecuted spend estimate for Sean.

## What was run

Clean current-main baseline, all EXPECTRAIL_* variables unset:
`python3 -m unittest discover -s tests -t .`: 4,086 tests, OK, 48 skipped,
307.296 seconds. Failing test names: none.

Round-one regression tests after applying the foundation: 16 tests, OK.
Focused new/JIT-withheld/package/foundation tests: 75 tests, OK in 11.776 seconds.
New and foundation tests with NumPy/Pillow imports blocked: 27 tests, OK in
5.520 seconds. No existing test file was weakened or skipped.
An early new hostile-text test wrongly expected an invalid action to generate a
check. Its two action subcases failed; corrected to assert none, refusal before
the model, and zero transport calls. The initial log is retained.

Real pinned-Godot body-flip gap: the round-one path returned not-reproduced after
three ground-check passes, while its trace's facing mismatch fraction was 0.7534.
Normal subprocess ingest --propose with a hand-picked stand-in model response:
generated-advisory, needs-review; the existing JIT record shows three clean passes
and three base failures, plus three failing unchanged-candidate runs. The model
was not live, and no fixer or paid API was called. Raw evidence is in the handover.

First full after suite (before adding the future-live binding guard test):
4,113 tests, OK, 48 skipped, 356.830 seconds. Final full suite, all EXPECTRAIL_* variables unset: 4,114 tests in 342.562 seconds,
OK, 48 skipped, exit 0. Failing test names: none. Final package/cap tests: 33 tests,
OK in 8.128 seconds. Final NumPy/Pillow-blocked run: 28 tests, OK in 6.000 seconds.
The new missing-cap test initially expected MODEL_UNAVAILABLE, but the in-process
runner's spend meter correctly publishes BUDGET_STOP. The corrected test asserts
the stop, its recorded reason, kind none and zero calls. That focused failure and
one short interrupted full-suite attempt are retained; neither is claimed green.

## Not done

No live proposer run, model-quality estimate, full producer report batch, paid spend,
fixer attempt, accepted repair, #271 counting/clearance extension, hosted CI or
GitHub write. No held-out or blind material, no approval changes, and nothing in
.github/, game/platformer, game/unity-platformer, gate/verify.py or anchored.py.
The other builder's unmerged report bundle was unavailable in this checkout;
this round's spend multiplication uses the one hand-written report actually run.
Live transport is bound only behind the existing explicit spec-role cap; no live
cap, credentials or API call were used. Stand-in responses bypass live transport.

## Files

- contracts/playtest-reproduction.v1.schema.json and its example
- contracts/verify-request.v1.schema.json and propose example
- contracts/verify-job.v1.schema.json and generated reproduction example
- contracts/jit-run.v1.schema.json and report-route example
- expectrail/contracts.py; expectrail/jit/intent.py, run.py, ingest.py
- expectrail/orchestrator/reproduction.py, playtest.py, cli.py, request.py
- expectrail/orchestrator/engines.py, runner.py, store.py
- tests/test_ingest_generated.py
- docs/playtest-propose.md and this work log
