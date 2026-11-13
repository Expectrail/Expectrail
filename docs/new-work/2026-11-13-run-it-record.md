# Run it: record each sample's vision answers from the Actions tab (#265)

## What changed
- `.github/workflows/run-it-record.yml`, "Run it record", asked for on #265 by the architect session.
  Sean dispatches it on main with a sample (a list of the manifest's three) and a spend cap (default
  $1.00, at most $2). Two jobs, as in `run-it.yml`:
  - `record`: `main-only` environment, `MODEL_API_KEY`, `contents: read`. Every replay sandboxed,
    `EXPECTRAIL_SAM_USD_CAP` set to the cap before `expectrail.runit record`. Uploads the recording and
    passes on the spend line.
  - `propose`: `contents: write`, no environment, no secret, runs nothing from the sample. Checks the
    recording with main's `expectrail.runit check-recording`, commits it to a new branch
    `run-it-vision/<sample>-<run id>`, and writes a link that opens the pull request, with the run and
    the spend in its description. Never pushes to main.
  - Decision: a link, not a pull request opened by the workflow. A pull request opened with the
    workflow's token starts no workflow, so the required checks (`private-export-scan` among them)
    would never run on it. This also means the workflow needs no `pull-requests: write`.
- `expectrail/runit.py`: `check-recording FILE --sample ID` (a usable recording, for this sample, in
  the manifest, with at least one answer), and `record` now prints `spend: $X at list price, N
  requests, M images answered`, also when the recording fails.
- `docs/run-it.md`: a section on the recording workflow.
- `tests/test_runit_record.py`: 15 tests.

## What was run
- `python3 -m unittest tests.test_runit_record tests.test_runit`: 41 tests, OK.
- The full suite: see the pull request description.
- The workflow's spend parsing and link building were run by hand in bash on a sample line.
- The workflow itself has not run: it runs on main only and spends money.

## Not done
- The recording runs themselves (Sean: about $1 in all).
- The workflow adds an `environment:` and a secret, so this pull request is `needs-sean` by AGENTS.md.

## Files
- `.github/workflows/run-it-record.yml`
- `expectrail/runit.py`
- `docs/run-it.md`
- `tests/test_runit_record.py`
- `docs/new-work/2026-11-13-run-it-record.md`
