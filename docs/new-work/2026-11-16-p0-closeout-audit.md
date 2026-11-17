# Audit five P0 issues and fix two small entry-point gaps

## What changed

Audited every original Done when case plus the Build/safety cases in #433, #422,
#329, #370 and #420 against main ec0919b60c03abf033ef79a996880300658e6887.
The close-out report has one table per issue, exact test/run/doc evidence and
explicit missing cases. #422 and #329 can close on the original scope; #433,
#370 and #420 cannot. Open #559/#570 are not counted as main evidence.

Fixed two small gaps: the repair CLI now forwards an explicit --agent choice to
the existing repair function (llm-patch or the unchanged Muse default), and app
inspection preserves the setup doctor's missing-engine/display/OpenGL warning
for live vision as well as recorded vision. No new generator, fixer, gate rule,
spend mechanism, approval or contract field. All existing live admission/caps
remain. The positive repair test uses an offline fixture and labels it as such.

The audit also names nontrivial missing integration: literal live auto-fix still
selects the refused Muse path; a public repair child request cannot carry an
original job's held-out routes; the fourth Run it card is unpublished and its
reader refuses the provider-only llm-patch provenance used by the new live kit.
Those are not solved by starting a paid run or relabelling its record. The app's
git selection, installer/first-user test and seven human re-approvals also remain.
Exact steps and evidence to retain are written for Sean without performing them.

## What was run

- Read AGENTS.md and all five issue bodies/comments. Read PR state for #548,
  #551, #555, #559, #570, #502, #516, #572, #410, #423 and #568. Read current
  workflow text for collection/isolation evidence; no workflow file changed.
- Required historical c169a5e0da304773587304ed47bc8aabcec80da7 fetch completed.
  Baseline full suite with no EXPECTRAIL_* variables:
  `python3 -m unittest discover -s tests -t .` — 4,509 tests, 488.829s,
  OK (58 skips), no failures/errors.
- Added regression tests before product edits:
  `python3 -m unittest tests.test_p0_closeout -v` — four tests, four failures
  across two methods (three suppressed tool warnings and the unrecognized
  --agent selector). The available-renderer and unknown-agent controls passed.
  After the two fixes: four tests pass, 1.624s, no skips. Red/green logs are
  linked from the audit. Local paths in committed excerpts are replaced and trailing spaces trimmed,
  explicitly labelled; hashes identify the unchanged raw handover logs.
- Focused existing audit plus new tests: 226 tests in 83.496s,
  OK (five prerequisite skips). Exact module list and verbose results are in
  the handover. No existing test assertion or skip changed.
- With numpy/PIL imports blocked and discovery reporting both unavailable:
  four new tests pass, no skips/errors/failures. No dependencies added.
- Four unchanged real Godot auto-route tests passed in 54.509s, no skips,
  using the existing installed 4.7.2 binary. Bundled and crate-run routes
  moved the player with three equal complete traces; independently randomized
  crate-run named ticks 0–242 and wrote no route. No game sources were edited.
  Exact portable command: set EXPECTRAIL_GODOT to the installed pinned binary,
  then `EXPECTRAIL_ENGINE_TESTS=required python3 -m unittest tests.test_auto_route_engine -v`.
- Literal `python3 -m expectrail.cli route --project PATH --auto --out ROUTE`
  on the bundled game and crate-run: both exit 0, three identical traces and
  movement reported, 2,094 and 243 ticks respectively. Logs/results linked in
  the audit. Real Godot, zero model calls.
- Read the historical first outside-vision capture/judge job status and spend
  log, plus #263's actual first-result comment. No live run was repeated.
  Read-only approval.state inventory: seven legacy live specs, one already
  bound outside check, three unapproved checkout drafts. No repository approval
  written; unchanged existing writer tests use temporary fixtures only.
- Final full suite: 4,513 tests in 580.345s, OK (58 skips), no failures/errors; no EXPECTRAIL_* variables.
- `python -m agents.export_scan bench docs README.md apps --paths error`:
  pass: 767 files, zero errors/warnings; prohibited blind directory excluded without reading and restored. Prohibited blind directory is excluded without reading
  contents and restored after the command; no private scan used.
- Final docs bytes, links/test names, protected-path audit, patch check and
  handover reconstruction: pass: docs remain below 256 KiB; exact byte inventory, link/method/scope audit and binary patch reconstruction are in the handover.

## Not done

No paid/live model, first-user trial, new visual recording, approval, workflow
dispatch/edit, repository setting change, push, GitHub comment or PR creation.
Sean must review/push the local patch. No private held-out/fresh/blind content
read. Protected gate/verify.py and anchored.py, .github, AGENTS and bundled game
sources are unchanged. No #566 migration or evidence-branch work duplicated #572.

#433 still needs the literal-command real-engine CI/live evidence, bounded
auto-fix agent integration/policy, held-out child-request integration, compatible
genuine fixer provenance plus publication of the fourth site sample, and the
reviewed draft-PR publisher. #370 still needs its git/working-copy selector and
installation/novice trial. A new outside unchanged accept is optional and needs
real recorded answers, not image substitution. #420 still needs Sean's seven
re-approvals with fixture-assumption updates in that human-owned change.
The existing tests passing now are not proof they will pass after re-approval.

## Files

- expectrail/repair.py: CLI agent choice passed to the existing loop.
- expectrail/renderer.py: retain missing-tool warning on live project inspection.
- tests/test_p0_closeout.py: four new fixture regressions; no existing tests edited.
- docs/app.md: actual probe behavior and current auto-fix refusal documented.
- docs/p0-closeout-audit.md: five tables, closure lines, remaining builder/Sean steps.
- docs/p0-closeout-audit/: small red/green and real-engine logs, approval inventory.
- This work log. Full suite logs and PR material remain in the handover zip.
