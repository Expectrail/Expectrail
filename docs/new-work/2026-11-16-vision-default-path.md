# Default verification requires visual evidence (#327)

## What changed

The raw gate API defaults to both observers; its command constructs a FramesObserver and retains
that policy when setup stops. The older verifier also defaults to visual checks, and its command
requires them even when the environment selects the engine-only benchmark counterfactual.
`expectrail verify`, sample and app verification already used both on this base.

Findings, verification and job contracts/examples carry observer adapter versions. The trusted
schema reader and job reader accept them; historical records remain readable. Two small evidence
checkers now expect the additional metadata. Their decision/evidence assertions remain intact.

The public fifteen-candidate benchmark can now use the shared gate, including decision B, through
`agents.verifier.judge_candidate`. It compares seed plus proposed fix against the clean reference,
using the existing approved public specs. A stand-in test verifies all fifteen trees and the
existing summary reader; it does not measure visual accuracy. The live dispatch instructions and
$56.25 maximum SAM budget are in docs/sam.md. Sean must review the named workflow edits first.

Docs and site describe the two-observer default. Historical benchmark measurements stay labelled
as historical; engine-only controls are diagnostic, not product clearance.

## What was run

The required historic fetch ran before changes. Full before: 4,654 tests, zero failures/errors,
60 named skips, 464.454 test seconds. Final after: 4,663 tests, zero failures/errors, 60 skips, 451.914 test seconds.
Failure/error names are empty before and after; there are no new failing names. Full logs and the
machine-readable name comparison are in the handover.

The default-path tests failed on the old implementation and passed after the changes. Focused
regressions exercise missing vision, scripted accepts/rejects, budget stops, old records, observer
metadata, explicit engine controls, all fifteen benchmark trees and the summary reader. Full test
discovery with NumPy/Pillow blocked loaded 4,765 tests with no import errors. Assertion AST comparisons cover 2,601 existing assertions: 2,595 unchanged, 6 expanded
only for metadata. The three saved findings reconstruct their exact prior bytes after removing
only the new metadata. Comparisons are included in the handover. Failed intermediate runs are retained too.

`python -m agents.export_scan bench docs README.md apps --paths error`: 834 files, zero errors
and warnings. The modified docs total less than 256 KiB; no bulk run evidence is added.

## Not done

No live model call, spend, benchmark dispatch, GitHub write or commit. The 8/8 good and 0/7 bad live
target is not measured. Native replay was not used for this offline slice. The site wording was
not looked at in a browser. No fallback order or decision-B rule changed. Ledger owners must add
the new offline tests without raising the evidence grade. The #257 remainder waits for PR #589.

## Files

- agents/verifier.py and expectrail/gate/verify.py: defaults, observer metadata, public benchmark adapter.
- Findings, verification and verify-job schemas and examples under contracts/.
- docs/sam.md, docs/ci-gate.md and docs/index.html: current policy and Sean's dispatch instructions.
- tests/test_default_vision.py: offline default-path and benchmark tests.
- Existing engine-fixture tests select the diagnostic rule/provider explicitly; metadata assertions
  and the clipped-player findings fixture include only the new version fields. FILES.txt and the
  PR body list each change and why its assertions retain their strength.
- tools/check_no_vision.py and tools/quickstart.py: readers of the updated observer metadata.
- This work log.
