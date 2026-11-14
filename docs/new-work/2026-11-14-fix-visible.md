# Show the recorded repair and verify its patch again (#433)

## What changed

Run it has a fourth sample for a live fix recording. Until a recording exists the card says “fix not recorded yet”. To replay a recording, Run it checks the parent game tree and winning patch digest, copies the seeded bug, applies that patch and verifies the copy against the bug. The gate uses its existing fix-demonstration rule and recorded vision answers. The fresh job decides the result.

The viewer shows the original reject, the attempts and their verdicts, the stop reason and the winning diff with the record's review label. The home and concepts pages show the sandboxed fixer, independent verification and human review in one diagram.

## What was run

- `python3 -m unittest discover -s tests -t .` ran 3,271 tests before (42 skipped) and 3,278 after (42 skipped). Both summaries ended in OK. Neither log contains a failing or erroring test name.
- The first full run found a broken fragment on both front-door pages. After linking the static samples heading, all five FrontDoorTest tests passed.
- The new offline tests initially ran six methods, with three failures and three errors.
- The focused run of the viewer, sample, recording, site, edge and link tests ran 109 tests, OK.
- The stand-in replays produced a fresh accept, reject and needs-review. A missing record made the shipped CLI exit 2 with “fix not recorded yet” and create no result directory.
- A Node check with offline responses verified that the fourth card stays disabled for a missing record and a fixture, and allows a run for synthetic live recording metadata. Both front-door diagrams were checked for their stages and captions.

## Not done

No live fixer recording was available. No model call, workflow dispatch or hosted run. Laptop and phone pages: not looked at. Chromium could not start because its local socket was refused.

## Files

- `apps/run-it-edge/service.js`
- `contracts/examples/run-it-samples.json`
- `contracts/run-it-samples.v1.schema.json`
- `docs/assets/front-door.css`
- `docs/concepts.html`
- `docs/index.html`
- `docs/new-work/2026-11-14-fix-visible.md`
- `docs/run-it.md`
- `docs/run-it/index.html`
- `docs/run-it/run-it.js`
- `docs/run-it/samples.json`
- `expectrail/diagnostics.py`
- `expectrail/orchestrator/engines.py`
- `expectrail/runit.py`
- `expectrail/viewer.py`
- `tests/test_runit.py`
- `tests/test_runit_record.py`
- `tests/test_visible_repair.py`
- `tools/runit_stub.py`

## Architect run (Linux, on arch/433-repair merged with main a5b7d950)
Applied cleanly. The page checker found one problem: the Run it page asked for `repair/repair-run.json`, which does not exist until a repair is recorded, so `check_pages` (CI's web-capture job) failed. Fixed by a `repairRecorded` flag in `samples.json` (false for now): the page asks for the record only once it is true. Full suite: OK, 31 skipped; page check: 10 pages, 0 problems; `runit run --sample recorded-fix` says "fix not recorded yet".
