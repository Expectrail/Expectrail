# Judge saved replays of an outside project (#422)

## What changed

Outside vision captures the pinned project and each listed change in a job with a read-only token.
Every replay requires Bubblewrap. The job uploads the replay records, traces and frames. Its digest
binds each record to the project commit, variant and route.

A second job checks that digest and verifies the trusted route, game tree, isolation record, frame
sequence and trace before asking the model. It runs the existing gate with saved replays and the
two-observer rule. The gate writes the game trees from capture into its findings. The Actions
summary uses the outside trial table and reports SAM requests, images answered and spend at list price.

## What was run

The required Git fetch succeeded. On unchanged main, `python3 -m unittest discover -s tests -t .`
ran 3,204 tests and ended OK with 42 skips. The first new test run failed on the missing judge
module. `python3 -m unittest tests.test_outside_vision -v` ran nine tests, OK. The tests use
saved fixture traces and PNGs and a stand-in observer. The integration test made any subprocess launch raise. The printed test spend came from the stand-in transport.

The after-suite ran 3,213 tests and ended OK with 42 skips. Comparing failure and error names
gave zero before and zero after. The workflow shell blocks passed `bash -n` and its summary
step wrote the verdicts and spend with a local fixture. The working-tree merge guard returned
the two expected needs-sean findings for the judge's secret reference and environment.

## Not done

No workflow was dispatched or paid model called. The workflow adds the MODEL_API_KEY secret
reference and the main-only environment. Sean must review and merge it, start the first
kinematic-character run and record its actual verdicts on #263.

## Files

- `.github/workflows/outside-vision.yml`
- `.gitignore`
- `agents/assurance/audit.py`
- `docs/new-work/2026-11-13-outside-vision.md`
- `docs/outside-projects.md`
- `expectrail/gate/verify.py`
- `tests/test_outside_vision.py`
- `tools/outside_vision.py`

## Architect run (Linux, main 25a96311)
Applied cleanly. Full suite: 3213 tests, OK, 31 skipped. `tests.test_outside_vision` and `tests.test_outside_trial` OK. Read the workflow: top-level `contents: read`; the capture job holds no secret and requires the sandbox; the judge job (`environment: main-only`, `MODEL_API_KEY`) checks out main without credentials, downloads the capture as data, checks its digest and never starts the game; the cap is checked in `tools/outside_vision.py` (above 0, at most $2). Not run live: that is Sean's dispatch after merging.
