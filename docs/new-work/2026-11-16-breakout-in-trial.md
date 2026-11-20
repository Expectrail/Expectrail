# Breakout in the registry-driven outside trial (#263)

## What changed

Root checkouts are accepted without allowing traversal, links out or copied git
metadata. Overlays refuse collisions with source config/routes/checks. Pointer
reports group clicks/sweeps while retaining every route event. Breakout is pinned
to the same public MIT commit; no game source was vendored.

The registry, its contract/example, trial writer and report reader now carry
explicit draft inputs, expected gate verdicts and expected raw engine findings.
Missing/mismatched evidence fails the trial, including an exit/decision mismatch.
Draft captures obey the same sandbox requirement as the CI verifier and never
construct a visual/model observer. No draft is silently treated as approved.

The paddle draft now requires two separated positions at ticks 20 and 70, in its
20..70 window; no frozen position can meet both. Bounds, paddle tolerance and ball
boundary are derived from the game and route. The [derivation and results](../outside-trials/breakout-ci/report.md)
state the remaining authored policy choices. Neither check has an approval.

## What was run

Before: **4382 tests, 469.476s, 0 failures, 1 error, 57 skips**. Final after: **4399 tests, 458.995s, 0 failures, 0 errors, 57 skips**. The first after run also passed (4399 tests, 521.400s). Failing names went from the one existing ingest-repair error below to `[]`; **no new failing names**. [Logs and comparison](../outside-trials/breakout-ci/validation/README.md).

The before run's existing ingest-repair test hit a captured-output JSONDecodeError;
its code/tests were not changed and the transient source is not diagnosed. The
handover retains all logs and compares failing test names.

Red root/summary run: 8 tests, 2 failures, 5 errors before implementation. The new
frozen-paddle assertion also fails against the old draft. Targeted suite: 84 tests,
3 named engine-prerequisite skips; contract/root/registry run: 42 pass; final guard:
37 pass. Imports work without NumPy/Pillow.

The real local runner fetched the pinned source and ran all three copies with
Godot 4.7.2/Xvfb. Gate: needs-review/needs-review/needs-review; zero approved checks.
Raw paddle: pass/pass/fail (first checked failure frame 20). Raw ball:
pass/pass/needs-review (movement prerequisite absent on broken). All declared
expectations passed. Total seconds: 58.3/59.8/50.7, including separate draft replays;
see the generated records. Diagnostic execution, no sandbox-isolation claim.

`python -m agents.export_scan bench docs README.md apps --paths error`: **1031 files, 0 errors, 0 warnings**, exit 0. The exact command and output are retained in the handover.

Repository evidence copies use portable path placeholders; the handover retains
original raw logs. No numerical evidence or trace bytes changed during redaction.

## Not done

The PR's **Outside projects trial / outside-trial** job has not run on this patch;
Sean must push/open the PR and read its conclusion and three Breakout rows. It
runs `python -m tools.outside_trial --fetch --execution-class isolated --out runs/outside`.
No workflow edit or dispatch. Sean alone reviews/approves the two drafts; exact
sentences, objects, windows, pass/fail meaning and commands are in the PR body.
No live model, vision accept, human timing, native macOS/Windows, approval, commit
or push. #263 remains open.

## Files

- `tools/outside_trial.py`, `expectrail/route.py`.
- `contracts/outside-projects.schema.json`, `contracts/outside-trial.schema.json`,
  and their examples.
- `tests/outside/projects.json`, both draft checks under `tests/outside/breakout-pointer/checks/`.
- `tests/test_outside_root.py`, `tests/test_outside_trial.py`.
- `docs/outside-projects.md`, `docs/outside-trials/breakout-ci/`, this log.
- Pending pointer/menu evidence under `docs/menu-routes-evidence/`,
  `docs/pointer-routes-evidence/`, `docs/outside-trials/breakout-pointer/`: path
  redaction only (plus notices), original logs retained in the prior handover.

The combined handover also includes the still-pending pointer/menu dependency;
its own file list and tree are separate. Main's newer Dodge documentation was
preserved when resolving the dependency's one documentation conflict.
