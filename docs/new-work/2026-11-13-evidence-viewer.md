# The evidence viewer, first slice: states, frames side by side, a timeline per check (#264)

## What changed
A new module, `expectrail/viewer.py`, writes a self-contained viewer folder (`index.html`,
`views.json`, `frames/`). It opens from disk and from a web site alike: the evidence is embedded in
the page, nothing is fetched, and a Content-Security-Policy refuses every request but the folder's
own frames.

- The gate writes `viewer/` beside `review/` on every run (`run_gate`). A viewer that fails to write
  prints a warning and changes nothing else: the decision, `findings.json` and the review page are
  written as before.
- `expectrail report JOB` writes the job's viewer to `jobs/<id>/viewer/index.html` for every
  finished job and prints the path. `report --json` is unchanged (the status alone).
- The page leads with one of ten states (accepted; rejected; needs review because an observer could
  not decide; because a replay did not finish; not verified because the project or request is not
  supported; because the run could not be carried out; because no check ran; cancelled; running;
  needs review). The job's decision wins over its record's; when they differ the page says needs
  review. An empty result, or a record saying accept over a check that did not pass, is never shown
  as accepted.
- It opens at the earliest finding's first failing frame: before and after side by side on the same
  frame number, six captured frames either side, keyboard stepping, overlays (the measured boxes and
  the boundary line) that can be turned off.
- A timeline per side of each check: the measured value against the tolerance, with missing and
  not-applicable frames marked. It is measured from the engine's record by the evaluator's rules
  (`viewer.series`, which imports the evaluator's helpers; `expectrail/evaluator.py` is not changed,
  it is pinned by the mutation study's registration) and is kept only when it agrees with the
  verdict (`series_agrees`); otherwise it is left out with a note.
- `setup.py` bundles the new module, since the gate imports it.
- `docs/viewer.md` describes it; `docs/orchestrator.md` says where `report` writes it.

## What was run
- `python3 -m unittest tests.test_viewer`: 19 tests, OK. They drive the real gate on the gate tests'
  stand-in replay (fixture traces, no Godot, no model) and the real worker and `report` command.
- `python3 -m unittest tests.test_package`: 17 tests, OK (the wheel holds the module and imports it).
- The full suite on the branch (main at 05d09e8 plus this change): see the pull request.
- Looked at in Chromium (Playwright) from `file://`, on a stand-in run whose frames were drawn from
  the fixture traces, at 1280 px wide and as an iPhone 13: both frames loaded under the CSP, no
  console errors, no request outside the folder, `→` `←` `f` `o` worked, no horizontal page scroll.
  The run-facts table cut off long commit ids on the phone; cells now wrap.

## Not done
- A single-file export that opens offline.
- A model-written explanation linked to evidence ids (none exists to link yet).
- The viewer for a real failing and a real passing Godot run published under `docs/` (needs the
  engine; this session had none), and the two-minute trial with one person.
- The visual observer's own timeline under the rule `both` (the timeline is the engine's record).

## Files
- `expectrail/viewer.py` (new)
- `expectrail/gate/verify.py`
- `expectrail/orchestrator/cli.py`
- `setup.py`
- `tests/test_viewer.py` (new)
- `docs/viewer.md` (new), `docs/orchestrator.md`
- `docs/new-work/2026-11-13-evidence-viewer.md` (this file)
