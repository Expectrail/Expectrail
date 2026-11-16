# Playtest report intake through the shared verifier (#531, part one)

## What changed

Added the closed `expectrail.playtest-report/v1` contract, example and bounded strict
reader/writer in `expectrail.orchestrator.playtest`. The embedded route is checked
against both the embedded contract and the current route schema. Reports replay
from the start, at most 1,800 ticks; unknown properties (including snapshots),
non-finite positions, malformed JSON and unsupported project engines are refused.
`target.commit` must match the project's Git HEAD; game tree digests still identify
the actual snapshotted bytes, including local changes.

`expectrail ingest REPORT --project PATH` uses the existing configured-project
snapshot and job store. It keeps every configured route and approved check,
adds a report route under a content-derived name, and captures only `bug` through
the existing bug-text field with intent `fix`. Producer strings and other report
text do not become check instructions, provider settings or policy selections.
No approval is written or changed.

The request's additional `coverage.reached` obligation uses `position-at-tick`:
exact physics tick, named world position, inclusive Euclidean tolerance. Supported
trace names are `player`, `enemy-N` and `projectile-N` (engine instance ids);
unknown or missing objects cannot satisfy the anchor. It is an additional replay
obligation, not a replacement for an approved spec's existing coverage.

The user authorized a small orchestrator precheck calling the existing `judge_arm` and
shared `coverage.all_of` assessor, because the protected verifier repeats only
already-repaired candidate comparisons. The existing `jit.assess.all_of` predicate
was moved unchanged into the packaged coverage module and re-exported by JIT, so
the installed intake does not depend on repository-only JIT modules. The unchanged base is replayed three
times; every anchor is checked before observation/evaluation. An off-anchor or
unobserved anchor ends needs-review with `anchor-desync`. Three complete passes
end needs-review with `not-reproduced`; missing evidence, no applicable approved
checks, and mixed outcomes remain inconclusive. A check failing on all three runs
proceeds to the existing `run_gate`, which alone decides accept/reject/review.
The CLI adds no fixer call. The existing repair command refuses a needs-review
parent; the intake does not enable auto-fix or introduce a model budget.

The normal two-observer rule remains in force. Engine-only mode is used explicitly
by the diagnostic rehearsal, not selected by report text or exposed by ingest.
The raw precheck traces stay in job work folders; its short result log is published
with job evidence. The extra coverage is included in request idempotency digests.

## What was run

Base: `e18dd3ef5267175166743c17a7b37480a292f3c0`.
The requested historical commit fetch completed. Untouched-base suite, with all
`EXPECTRAIL_*` variables removed: `python3 -m unittest discover -s tests -t .`:
4,028 tests in 319.726 seconds, OK, 47 skipped, exit 0. Failing test names: none.
An earlier baseline attempt was interrupted after draft edits began. Those drafts
were saved outside the checkout, every change was restored, and this completed
baseline was run with a clean `git status` before restoring the implementation.
The interrupted log is retained separately and is not counted as a baseline.

Focused final run:
`python3 -m unittest -v tests.test_playtest_contract tests.test_playtest_ingest tests.test_schema_pattern tests.test_exercised_coverage tests.test_verify_intent`:
68 tests, OK in 5.760 seconds. New contract/intake tests with NumPy and Pillow
imports blocked: 16 tests, OK. The first dependency-simulation attempt incorrectly
made `find_spec('PIL')` raise instead of returning None; the corrected simulation
and its log are retained. The normal tests were not failing on those dependencies.

Real-engine rehearsal:
`PATH=/workspace/work/531/x11/root/usr/bin:$PATH python3 tools/playtest_ingest_rehearsal.py --out /workspace/work/531/real-engine-final`.
Pinned Godot 4.7.2-stable, SHA-512 checked, reported
`4.7.2.stable.official.ed1daf0bf`. The real public air-jump report ran through
three base judgments and ended needs-review / `not-reproduced`: the unchanged
approved ground check passed 3/3, and does not test extra jumps. A report with its
anchor moved 1,000 px ended needs-review / `anchor-desync` after one base replay.
A false floor-fall report on the clean game ended needs-review / `not-reproduced`
after 3/3 passes. Every budget recorded zero holds and no model-request phases.
This explicitly engine-only diagnostic rehearsal uses the actual public CLI,
store, harness, captures and shared judge; worker launching runs in process.

The normal subprocess command, `python3 -m expectrail.cli ingest` with the same
real report/project, ended needs-review / reproduction-inconclusive without
visual evidence. A separate scripted two-observer run passed the check 3/3 and
ended `not-reproduced`, with no HTTP or fixer call (360 synthetic visual answers;
not real model evidence). NumPy/Pillow-free tests also passed.

Early rehearsal attempts failed on an incorrect texture extension and then
missing `xvfb-run`. The system package install was read-only; Debian Xvfb packages
were downloaded and extracted into work/ instead. The pinned binary was fetched
through the repository helper and its SHA-512 checked. An initial normal-command
invocation used nonexistent `python3 -m expectrail`; the corrected module is
`python3 -m expectrail.cli`. These logs are retained apart from successful runs.

The first full after run found one packaging failure:
`tests.test_package.ContentsTest.test_every_module_in_the_wheel_can_import_what_it_asks_for`.
It ran 4,096 tests in 511.041 seconds, with one failure and 36 skips. The intake
imported `expectrail.jit.assess`, which is deliberately excluded from the wheel.
Moving the unchanged shared predicate into coverage fixed that dependency.
Package/intake/coverage follow-up: 62 tests, OK in 7.536 seconds. The new tests
with NumPy/Pillow blocked passed again: 16 tests, OK in 2.288 seconds. The failing
suite and isolated package failure logs are retained. Final full suite, all `EXPECTRAIL_*` variables removed:
`python3 -m unittest discover -s tests -t .` — 4,096 tests in 520.656 seconds,
OK, 36 skipped, exit 0. Failing test names: none. Godot had been downloaded between
the clean baseline and after runs; both recorded environments and their counts
are retained. The real-engine rehearsal was refreshed on the final code with the
same three outcomes and zero model holds.

## Not done

No push, GitHub comment, PR or hosted CI run. No live model/fixer/provider call,
credentials, spend, held-out material or blind set. No changes under `.github/`,
`game/platformer`, `game/unity-platformer`, `expectrail/gate/verify.py` or
`expectrail/anchored.py`. Rules 4 and 5 retain the existing behavior; this intake
adds no held-out or advisory-discovery feedback path.

The producer and published filter-count benchmark belong to the other part of
#531. The report is not mapped to a bug family or a generated/approved check.
An air-jump report therefore cannot be reproduced by an approved ground-only
check merely because its text describes an extra jump. No end-to-end fixer rate
or acceptance is claimed. The rehearsal's engine-only diagnostic results do not
stand for a production two-observer verification; absent visual evidence remains
inconclusive in the production path.

## Files

- `contracts/playtest-report.v1.schema.json`, `contracts/examples/playtest-report.json`
- `contracts/verify-request.v1.schema.json`, `contracts/examples/verify-request-playtest.json`
- `contracts/test-spec.schema.json`, `contracts/examples/test-spec-anchor.json`
- `expectrail/orchestrator/playtest.py`, `expectrail/orchestrator/request.py`
- `expectrail/orchestrator/cli.py`, `expectrail/orchestrator/engines.py`
- `expectrail/coverage.py`, `expectrail/jit/assess.py` (shared predicate relocation)
- `expectrail/cli.py` (one registration line)
- `tests/test_playtest_contract.py`, `tests/test_playtest_ingest.py`
- `tests/test_schema_pattern.py` (one sample for the new required id pattern)
- `tools/playtest_ingest_rehearsal.py`
- This work log
