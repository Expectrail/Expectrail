# Capability ledger and release dossier refresh (#244, #268)

## What changed

Based on main 21fde1b4be9362d209852e3d44221d059d110643, after PR #569.
The offline ledger guard reads README, every top-level Markdown doc, and the existing
HTML surfaces: 69 files, 46 rows. It checks page ownership as well as command,
switch, workflow and watched-name references. Installed CLI examples also require
explicit ownership for ingest/propose/repair, automatic routes and verification intent.
Unimplemented Unreal support is explicitly a roadmap row. Administrative commands
and non-mode protocols have stated reasons. No row was promoted to measured.

The dossier keeps historical cohorts and results separate, adds all subsequent
merges through this baseline (#573, #582, #583, #585, #586), checks every recovered
public baseline file digest and each published defect count, and derives the frozen
sensor summary from the committed frame rows. It checks the frozen plan identity
and pixel-only proof scope. It does not pretend to revalidate missing full captures.
The previously missing recovered-score claim is corrected. UI integer observations,
partial enemy boxes, exact renderer limits and the unrun nightly are explicit.

The README links the ledger and regenerated dossier. The site already links the
dossier; its generated summary and release artifacts were regenerated offline.
The existing CI unittest discovery runs the ledger tests; no workflow change or
workflow proposal is needed. Source changes are confined to expectrail/capabilities.py,
tools/dossier.py and their tests. The original negative assertions remain: tests
remove newly legitimate ownership in their fixtures when testing unknown names.
The inventory assertion expands from four fixed pages to all public root docs.

Guard: test change intended (#244)

## What was run

The required historic c169a5e0da304773587304ed47bc8aabcec80da7 fetch completed.
Before any source changes, with all EXPECTRAIL_* variables removed:
python3 -m unittest discover -s tests -t .
4,654 tests in 784.479 seconds; FAILED (failures=2, skipped=60).
Failures: tests.test_orchestrator.ProcessTest.test_waiting_on_a_worker_that_died_reports_it_at_once;
tests.test_replay_sandbox.DiskBoundTest.test_a_folder_the_game_makes_unreadable_is_cannot_tell.
This is the same untouched main baseline recorded for the preceding Task 0.

Focused command: python3 -m unittest tests.test_capabilities tests.test_capabilities_docs
 tests.test_dossier tests.test_dossier_truth tests.test_dossier_refresh
88 tests passed in 8.863 seconds. Includes unknown documentation/modes, symlink
refusal, fixture ownership, existing CI hook, frozen plan/frame/summary/proof drift,
recovered-byte/total drift, deterministic regeneration and no numpy/PIL/network build.

Regenerated with python3 -m expectrail.capabilities render and python3 -m tools.dossier
--commit 21fde1b4be9362d209852e3d44221d059d110643.
python3 -m expectrail.capabilities check and python3 -m tools.dossier --check passed.
The dossier reads 58 explicitly allowlisted public inputs; it does not crawl the bench.
After: 4,668 tests in 809.126s; FAILED (failures=1, skipped=60).
After failures: tests.test_orchestrator.ProcessTest.test_waiting_on_a_worker_that_died_reports_it_at_once.
Both full logs, failure names, focused output, offline checks and export results are
in the patch zip test.log. Patch application against BASE and whitespace checks passed.
Public export scan: zero errors and warnings. Documentation additions are below 256 KiB;
existing large evidence stays on main and is not copied into this patch.

## Not done

No new product measurement, engine benchmark, live model call, spend, dispatch,
first-user test, deployed nightly smoke, later reproduction rate, release tag,
image digest or billed per-profile cost was collected. The earlier untuned
8/341 (2.35%) sensor alarms and failed cross-game transfer remain; the frozen
closeout's 4/227 new-pixel clean alarms are a different bank/cohort, not a replacement.
The historical public baseline is candidate-shown, not candidate-withheld proof.
Nightly code and fixture tests are not a deployed result. Runtime samples remain
non-comparable singletons; no p50/p95 is invented.

No push, PR, comment, approval, workflow, game, verifier/orchestrator code or private,
blind-set or fresh-* content was changed/read. Task 0's command patch remains a
separate handover and is not represented here as merged product behavior.
Existing untied aggregate notices and human status/grade review remain open. No online
run recheck, CI permission change or independent re-scoring of historical aggregates was made.
The full suite must be assessed from its recorded failures; no assertion was weakened.

## Files

- README.md
- expectrail/capabilities.py; tools/dossier.py
- tests/test_capabilities.py; tests/test_capabilities_docs.py; tests/test_dossier_refresh.py
- docs/capabilities.json; docs/capabilities.md; docs/index.html
- docs/release/index.html; docs/release/sources/capabilities.json
- docs/release/figure-changes.json; docs/release/truth-pass.md
- docs/new-work/2026-11-16-ledger-dossier.md
