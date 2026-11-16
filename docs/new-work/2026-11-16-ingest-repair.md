# Opt-in repair after an approved playtest reproduction (#531)

## What changed

Applied the local round-one/two ingest foundation to current main, retaining main's
commit-input resolution. Added foreground `ingest --repair`, calling the shipped
#433 `expectrail.repair.repair` service after checking the recorded approved 3/3
base proof. Added repair-run intake metadata and truthful review labels for
blocked/unsuccessful runs. Generated advisory, unreproduced and anchor-desynchronised
reports cannot start a fixer. Candidate discovery-run findings and existing generated-check catches stop for named
needs-review without retry, preserving the gate decision separately. Fresh child
requests retain trusted configured visual settings.

Synthetic integration tests cover the real store, gate/evaluator and fixture
repair loop, hostile text, no transport construction on blocked paths, and a
held-out-only veto whose private route/frame/reason canaries never enter the
fixer workspace or retry. No held-out data was used. See `docs/ingest-repair.md`
for the unexecuted spend estimate and the trusted discovery artifact boundary.

## What was run

Before edits, with every EXPECTRAIL_* variable removed:
`python3 -m unittest discover -s tests -t .`: 4,161 tests, OK, 49 skipped,
339.956 seconds, exit 0. Failing test names: none.

Adapted foundation: 28 ingest contract/integration/generated tests passed.
Initial round-three run: 9 tests, one failure in
`tests.test_ingest_repair.IngestRepair.test_generated_advisory_requires_person_and_constructs_no_transport`.
The test had replaced snapshotting with a no-op and omitted the generated record's
required digest. Fixed the stand-in setup; no production keep rule changed.

The first full after-suite ran 4,200 tests and failed
`tests.test_commit_inputs.CommitInputsTest.test_sha256_repository_resolves_full_ids_and_trees`.
My foundation merge had restored the older 40-character commit restriction.
Restored main's head/base definitions and commit-selector constraint; all main
common request/job schema properties now match main exactly. The 50 focused
commit-input/contract/repair tests passed, followed by a full core suite of
4,200 tests, OK, 49 skipped (343.857 seconds).

The additional existing generated-check flag test initially used an invalid id
without the required `jit-` prefix; the strict reader refused it. Corrected the
stand-in, without changing that reader or its contract.

Final focused run including commit inputs: 79 tests, OK (30.502 seconds).
With numpy and PIL hidden from discovery and imports actively blocked: 49 tests,
OK (26.264 seconds).
No new skip was needed: these tests use stdlib synthetic frames and transports.

A separate recorded offline CLI run captured approved acceptance, not-reproduced,
anchor-desync and a candidate advisory veto. The handover includes the four
repair-run records, public precheck proof and accepted child findings; all use
synthetic replays and scripted vision with live networking/gateway construction
blocked. The added advisory example passed the strict contract reader.

Final full suite, with every EXPECTRAIL_* variable removed:
`python3 -m unittest discover -s tests -t .`: 4,201 tests, OK, 49 skipped,
370.756 seconds, exit 0. Failing test names: none. Combined and split patch
application checks reconstruct the staged tree exactly; scope audit finds no
protected-path or approval-value change.

## Not done

No live model/API calls, fixer CLI or real-engine run this round. Fixture candidates
exercise the existing loop with stand-in replays and vision; they do not prove a
live sandbox invocation. No private or blind material read, no approval changed,
no game source edited, no GitHub writes, no push or PR. Discovery is consumed when
trusted candidate verification emits its existing record; this change does not
schedule a new discovery run. Foreground repair only. Spend figures are unexecuted
reservation estimates; the existing Muse hold is not a token-bill ceiling.

## Files

Round-three files: `contracts/repair-run.v1.schema.json`,
`contracts/examples/repair-run-ingest.json`,
`contracts/examples/repair-run-ingest-blocked.json`,
`contracts/examples/repair-run-ingest-advisory.json`,
`expectrail/orchestrator/cli.py`, `expectrail/orchestrator/ingest_repair.py`,
`expectrail/repair.py`, `tests/test_ingest_repair.py`, `docs/ingest-repair.md`,
and this log. The combined handover also includes the earlier foundation; its
separate patch and work logs retain their original scope.
