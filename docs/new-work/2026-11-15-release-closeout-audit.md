# Release suite, two-job Action and orchestrator closeout audit (#258, #254, #250)

## What changed
Read all three issues' Done when and comment history, then audited current main
`ec4c1f55bd077f0be42ead2a777697ac0b11a6c4`. The supplied branch started at e18dd3e and was fast-forwarded locally
over #530 before edits. The complete control/case/evidence tables and Sean's exact
remaining steps are in [release-closeout-audit.md](../release-closeout-audit.md).
The historical AGENTS fetch had already been performed in the shared repository.

The trusted bundle reader now requires exactly the route's scheduled frame indices
and stable positive PNG dimensions within each replay, before any observation.
It previously accepted an extra duplicate frame with consistent digests, and did
not refuse a mid-replay resolution change at the evidence boundary. The PNG header
check uses only the standard library. No image tolerance, model fallback, observer
threshold, bank, protected grade or approval changes.

Added two offline reader regressions and two real-process release-gate cases.
The process tests are scoped partial guards on the duplicate/resolution rows:
equal-count stale content, independent capture geometry and tick binding are still
open. Legitimate stationary frames may have identical hashes; they are not banned.
The positive person-approved contract-change row now remains open when only its
two negative tests pass. A new regression proves the earlier false held status.

Guard: test change intended (#258). Open rows may retain explicitly scoped passing
negative guards without pretending the full positive case is demonstrated. The
table-format test now permits that documented case; failed tests still fail the
summary before its open-reason rule. No test was removed or newly skipped.

The published release report is regenerated from the original 52-test main CI
record, with an explicit audit correction: original 23 held / 12 open, corrected
22 held / 13 open. Every recorded test outcome is unchanged. The current suite has
54 bodies; no new test is pretended to have run in that old CI run. The JSON names
the source run/artifact/hash and correction; the Markdown is its normal render.

## What was run
- Baseline full suite before production changes: 4,028 tests in 339.032s,
  OK (47 skipped), no failures/errors.
- Two new unit tests on the original reader: both fail because no ValueError was
  raised. `logs/red-bundle-shape.log` preserves the red run.
- Positive-intent summary regression on the original control table: fails
  held != open (`logs/red-intent-claim.log`), then passes after the correction.
- Real-process red/green: downloaded only PR #514's public capture, artifact
  14183043214 (87,035,986 bytes), and verified GitHub's SHA-256
  `09b636dcd7ce1b39e9eb27c8a12d89ca23e9c13023f5fb0992e701afcebd4d07`.
  The unchanged archive accepts on both readers. The two actual new EvidenceTest
  bodies fail on a separate base checkout's old judge, and pass on this patch's
  real judge subprocesses. Only setup/driver configuration supplies saved hosted
  captures instead of fresh local replays; all refusal assertions are unchanged.
  Red: extra-frame capture accepts; resolution change reaches needs-review rather
  than EVIDENCE_MISMATCH. Green: both are refused before observation. No model or
  new engine run. Scripts, provenance and full logs are in the handover.
- Focused release-gate, CI-gate and dossier checks: 128 tests, OK in 18.078s.
  Three new main regressions also pass with numpy/PIL unavailable (0.512s).
  Full discovery has zero import errors with both absent; all 54 release bodies
  load. The initial missing-dependency harness incorrectly raised from find_spec;
  it was corrected to return None, matching a genuinely absent optional module.
- One intermediate full green run: 4,031 tests, 342.410s, 47 skips. A subsequent
  intermediate run caught one unchanged table assertion after an unnecessary own
  baseline was attached to each always-open partial row. Those redundant baseline
  entries were removed; the existing assertion and all tests were retained. That
  failed log (4,031 tests, 393.163s, one failure, 47 skips) remains separate.
- Final `python3 -m unittest discover -s tests -t .`: **4031 tests in 386.591s, OK (47 skipped)**.
  Zero EXPECTRAIL_* variables in the shell; no process-wide cap or opt-in model
  setting was introduced. Existing prerequisite skips are not new evidence.
- Main CI release-gate run 43766766042/job132973564224: 52 test outcomes,
  no skipped/failed/unrun controls; downloaded the 8,820-byte summary artifact and
  verified SHA-256 `fc70fc1d38c851de043e83fa3c3ce08c6b1ab6ceb3d053a3a4d339ec24f60a8f`.
  Its original Markdown reproduced byte-for-byte from the original JSON. The
  audited report preserves those outcomes and labels its classification correction.
- Read-only GitHub evidence confirms a real hosted candidate and trusted judge on
  #514, with accept/evidence-success/clearance-success from expectrail-checks.
  The older head has evidence-success/clearance-failure for workflow identity.
  This corrects the uncited hosted-accept gap from #244, without claiming a seeded
  fix, fork, tamper or branch-enforcement trial. Branch protection read returned
  403; the existing docs say clearance is advisory on Expectrail.
- `git diff --check` passes. Exact-base patch application, changed-file hashes and
  zip integrity are verified before delivery; the handover records those checks.

## Not done
Closes #258 as its **suite inventory**, per the explicit Done when allowance for
open controls. Thirteen controls remain open; this is not release readiness.
The two added real-Godot suite tests must also run in the integrator's required
release-gate job on this patch, normally before merge. The local saved-capture
tests do not claim a new local Godot capture or a hosted run of this patch.

Part of #254: controlled hosted seeded-correct/wrong-fix, deliberate between-job
tamper and new-head trials remain. Fork behavior and actual protected-branch
enforcement remain unproven. The exact App/environment/rule/trial steps are in the
audit. The existing advisory policy is not changed.

Part of #250: commit-reference resolution (rather than checkout paths and declared
commit metadata), shared job-service migration for legacy MCP/Action entry points,
and a supported trusted private-suite input remain. These need an integration and
request-boundary design, not a small audit fix or an unreviewed workflow edit.
The separate receipt-controls builder's three rows are not duplicated.

The 87 MB public capture is not embedded in the code zip: the handover gives its
run/artifact/hash and download/reproduction instructions. The small original CI
summary artifact is included. No new repository, push, PR, GitHub comment, workflow
dispatch, live model, secret change, approval, fresh-* material, blind-set content
or private held-out repository was used. No .github, tools/merge_guard.py,
expectrail/gate/verify.py or expectrail/anchored.py file changed.

## Files
- `tools/ci_bundle.py`
- `tests/capture_edits.py`
- `tests/release_gate/controls.py`
- `tests/release_gate/gate_bundle.py`
- `tests/test_ci_gate.py`
- `tests/test_release_gate.py`
- `docs/release-gate.md`
- `docs/measurements/release-gate-audit-results.json`
- `docs/release-closeout-audit.md`
- `docs/new-work/2026-11-15-release-closeout-audit.md`
