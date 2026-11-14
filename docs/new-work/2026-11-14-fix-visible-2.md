# Show recorded repairs in Run it and the viewer (#433)

## What changed

Run it has a fourth card for a recorded repair. While it is unpublished, the card says “fix not recorded yet”. The viewer reads the repair writer’s record and shows the attempts, stop reason, winning diff and review label. Replaying the sample uses the seeded bug and a patched copy. Its fresh verify job supplies the verdict. The home and concepts pages show where the fixer stops and the person reviews.

## What was run

- `python3 -m unittest discover -s tests -t .` ran 3,383 tests before and 3,395 after. Both summaries were OK with 42 skips. Neither run had a failing or erroring test name.
- `python3 -m unittest -v tests.test_visible_repair tests.test_repair_command tests.test_runit tests.test_runit_record tests.test_runit_site tests.test_runit_links tests.test_runit_edge tests.test_viewer tests.test_quickstart` ran 131 tests, OK.
- Before the port, the writer-to-reader test produced a fixture repair, then failed because the viewer lacked `read_repair`. It passed after the port.
- `python3 -m expectrail.runit run --sample recorded-fix --out DIR` exited 2 with “fix not recorded yet” and produced no result directory.

## Not done

No live fixer recording or new vision answers. No paid model, real Godot replay or workflow dispatch. The pages were not looked at in a browser. The default Playwright executable was absent and system Chromium could not create its socket.

## Files

- `apps/run-it-edge/service.js`
- `contracts/examples/run-it-samples.json`
- `contracts/run-it-samples.v1.schema.json`
- `docs/assets/front-door.css`
- `docs/concepts.html`
- `docs/index.html`
- `docs/new-work/2026-11-14-fix-visible-2.md`
- `docs/run-it.md`
- `docs/run-it/index.html`
- `docs/run-it/run-it.js`
- `docs/run-it/samples.json`
- `expectrail/diagnostics.py`
- `expectrail/runit.py`
- `expectrail/viewer.py`
- `tests/runit_repair_card.cjs`
- `tests/test_repair_command.py`
- `tests/test_runit.py`
- `tests/test_runit_record.py`
- `tests/test_visible_repair.py`
- `tools/runit_stub.py`
