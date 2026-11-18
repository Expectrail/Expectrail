# Trusted CI receipt producer and attestation proposal (#255)

## What changed

Added a thin recorded-CI producer and an end-to-end receipt checker under the
owned gate package. The producer reuses `expectrail.receipt/v1`, the strict gate
record reader, the existing bundle reader and existing receipt signer/reader.
The schema's field constraints are unchanged; descriptions state this producer's
commit/policy/artifact encodings. The new example comes from an offline fixture,
with no genuine GitHub attestation and no trusted issuer by itself.

The producer binds trusted PR state and the judged capture/result, carries the
original gate decision, hashes capture/report artifacts, and keeps its ephemeral
key only in memory. The checker uses the existing pinned `gh`/attestation reader
and trust-check implementation, and additionally verifies every named disk
artifact. Missing/changed/unsafe evidence cannot clear. The only supported
producer profile is the current recorded-vision CI path with $0 model API cost.
There is no live observer/fixer accounting or new replay/decision/fixer loop.

A complete workflow proposal, never installed, adds attesting permissions only to
the existing trusted job. It pins the observed official actions/attest v4 commit,
retains its public bundle, and requires receipt/attestation/proof/report success
before clearance publication. It preserves an earlier EVIDENCE_MISMATCH instead
of replacing it with an attestation error. Docs explain independent pins, raw
capture download, 24-hour expiry and the exact human installation/test update.

Guard: test change intended (#255)

Reason: additive producer/checker/proposal regression tests; no existing assertion
was loosened or skipped. The existing unittest main guard moved to the end so its
script entry includes the previously appended split/head classes and new fixtures.
The existing current-workflow permission assertion remains exact and unchanged;
its future permission update belongs with Sean's actual workflow installation.

## What was run

- Read current AGENTS.md, #255 and all 18 comments, existing receipt/attestation APIs, CI producer/publisher and relevant tests. Sean was told when this task started; no claim was posted by the builder.
- New local `chatgpt/255-attesting-step` from latest main `401236c97bdd9bbe80377dcdb92c78747ece878c`. Required historic fetch succeeded once.
- Full before, no EXPECTRAIL variables: 4,714 tests, 504.258s, OK (60 skipped), exit 0.
- Initial red: nine new tests error on the missing producer/checker module. A later meaningful integration red catches the wrong assumption that the real CI directory is named report; the fixed test runs the actual write command on expectrail-report.
- Initial producer/checker cases: 11 tests, 12.100s, OK. Final new cases after proposal checks and actual write/check commands: 12 tests, 10.455s, OK.
- Receipt/attestation plus new cases: 75 tests, 14.730s, OK. Intermediate new-test selection error (optional step name) is retained separately and fixed without loosening any assertion.
- An existing-fixture probe used the existing six-replay split-gate case with numpy/PIL imports/detection blocked: 1 test, 0.934s, OK. Remaining optional-dependency, full-after and export results are recorded in the final handover.
- First full after: 4,726 tests, 552.324s, one unchanged timing failure (60 skipped): `tests.test_orchestrator.ProcessTest.test_waiting_on_a_worker_that_died_reports_it_at_once`, 0.5305s versus 0.5s. No assertion/cleanup code changed.
- Review added a meaningful red for the $0 profile: a live-provider-stamped stand-in was accepted despite the flag. The producer now also requires the recorded-bank marker. Final guarded receipt/attestation/new tests: 76 tests, 15.701s, OK. Final blocked numpy/PIL run: 76 tests, 20.035s, OK. An intermediate stand-in accessor error is retained and corrected without loosening assertions.
- Final native full after, guarded code unchanged and no EXPECTRAIL variables: 4,727 tests, 618.450s, FAILED (1 failure, 60 skipped), exit 1. The same unchanged `tests.test_orchestrator.ProcessTest.test_waiting_on_a_worker_that_died_reports_it_at_once` took 0.582838s versus 0.5s. Host process scans see over 11,000 existing PID-1 zombies; no worker code or timing assertion was edited.
- Same timing test, same interpreter/source, fresh local Docker PID namespace: 1 test, 0.148s, OK. Diagnostic full run in that minimal profile: 4,721 tests, 427.735s, FAILED (5 failures, 12 errors, 71 skipped). Missing node/ffmpeg runtime/Chromium and Git configuration plus Python PID 1 affect unrelated cases. Every failing name and output is retained. This is not an equivalent green suite. Read-only source/runtime mounts, no network/image pull/home/credential mounts. Initial --init probe failed before testing; subsequent probe omitted it.
- Guarded offline command rehearsal: 6 stand-in replays, 360 stand-in vision questions, 5 fake gh verifications, zero live model/GitHub-verification requests. Matching evidence exits 0; altered capture exits 1; original capture restored. All named artifacts match the signed fixture. No genuine CI attestation exists.
- Required export scan: 854 files, zero errors/warnings, with the opaque blind/fresh entry held aside unopened and restored. Patch/hash/scope checks are recorded in the handover. Alternate-index application of original PR #588 plus the three task patches succeeds; this proves applicability only, not a combined-tree suite run.
- Official actions/attest v4 tag and action.yml read anonymously, 2026-11-17: commit 1e69f48acb82d1966a394da916b4c1698aa569d6, action.yml blob f3d593f3020cf14b65d2789e3788d015354475e9. Confirmed custom predicate inputs and bundle-path output; no action or workflow executed.

## Not done

Native full-after remains red on the unchanged worker timer. Rerun `python3 -m unittest discover -s tests -t .` on a clean runner before opening this PR; the container diagnostic does not replace that run.

Part of #255. Sean must install/review the permission-bearing proposal and its
exact permission-test update, then obtain and verify a real CI receipt. No real
Sigstore proof or hosted receipt verification is claimed: gh outputs are stand-ins.
Creating/publishing a first permanent offline issuer key/store remains Sean's
separate action; the CI attestation path uses its in-memory per-run key.

No workflow, observer, verifier, onboarding, app, capability, README, approval or
game-source edit; no live model, spend, dispatch, push, PR or GitHub write. No
private repository, held-out, blind or fresh content was read. No source check
was approved. This receipt proves the stated issuer/bytes/coverage within the
existing gate, not check-set completeness, capture authenticity beyond that
pipeline, a live vision measurement, hosted fork secret isolation or repair rate.

## Files

- `contracts/receipt.v1.schema.json`: descriptive CI mapping, unchanged field constraints.
- `contracts/examples/receipt-ci.v1.json`: offline producer example, no genuine attestation.
- `expectrail/gate/ci_receipt.py`: existing-contract producer and composed checker.
- `tests/test_ci_gate.py`: additive offline and process/CLI tests; main guard at end.
- `docs/proposals/255-trusted-receipt.yml.txt`: complete person-only workflow proposal.
- `docs/ci-gate.md`: installation, encodings, independent verification and limits.
- This work log; raw logs and offline rehearsal artifacts stay in the handover zip.
