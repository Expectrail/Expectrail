# Run it, slice 1: the workflow, the samples, recorded vision answers, the same run offline (#265)

## What changed
- `.github/workflows/run-it.yml`: dispatched on main with a sample id and a request id. Job `verify`
  (contents: read, no secret) replays the sample in the replay sandbox and uploads its folder; job
  `publish` (contents: write) runs no sample code, checks the folder against an allowlist with main's
  `expectrail.runit check`, and commits it to `run-it-results/<request id>/`. `concurrency: run-it`.
- `docs/run-it/samples.json` with its schema (`contracts/run-it-samples.v1.schema.json`): the three
  samples (the game as it is, the seeded fall-through bug, its repair).
- `expectrail/recorded.py`: `RecordedObserver` (the `FramesObserver` interface over a client that
  answers only from a recording, keyed by frame SHA256 and exact prompt; anything else is no answer),
  `RecordingClient` (wraps a live client during the one recording run), and the recording contract
  `contracts/vision-recording.v1.schema.json` with its example, writer and reader.
- `expectrail/runit.py`: `run` (the same run offline, two-observer rule, writes `status.json`,
  `findings.json`, `viewer/`), `check` (the publish allowlist), `record` (the live recording run, for
  Sean). `status.json` is `contracts/run-it-result.v1.schema.json`, with its example.
- CI's `seeded-bugs` job runs `expectrail.runit run --expect` and `check` on all three samples with
  real Godot replays, each sandboxed, and keeps the folders as the `run-it-offline` artifact.
- `docs/run-it.md`.

## What was run
- `python3 -m unittest tests.test_runit`: 26 tests, OK. Stand-in replays and a recording made from the
  scripted stand-in model (SAM 3.1's wire format), not recordings of the live model. No Godot, no model.
- The full suite on the branch: see the pull request.
- The real-engine CI step had not run when this was written.
- The workflow `run-it.yml` itself has not run: it runs on main only, after merge.
- Not looked at in a browser: this slice has no page of its own (the viewer folder is #264's page).

## Not done
- No sample has a vision recording yet: Sean dispatches one live run per sample (about $1 in all).
- Slice 2 (the Run it page against a local stub, the latest finished run per sample), slice 3 (the
  edge function, quotas, burst test).

## Files
- `.github/workflows/run-it.yml`, `.github/workflows/ci.yml`
- `contracts/run-it-samples.v1.schema.json`, `contracts/run-it-result.v1.schema.json`,
  `contracts/vision-recording.v1.schema.json`, `contracts/examples/run-it-samples.json`,
  `contracts/examples/run-it-result.json`, `contracts/examples/vision-recording.json`
- `docs/run-it/samples.json`, `docs/run-it.md`
- `expectrail/recorded.py`, `expectrail/runit.py`
- `tests/test_runit.py`
