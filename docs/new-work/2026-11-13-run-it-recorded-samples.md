# Run it: every sample has its recording, shown on main by three real runs (#265)

## What changed
Sean's three recording runs were merged as #403, #404 and #405. The text that still said "no sample has
a recording" is now what the runs show:

- `docs/run-it.md`: names each sample's recording and the run it came from, says what the samples
  decided before them, and that a frame the recording does not hold gets no answer.
- `docs/capabilities.json` (and the rendered `docs/capabilities.md`), row `run-it`: four new runs as
  evidence (below); the limits no longer say no sample can be accepted. The status stays `implemented`:
  a visitor still cannot start a run, because the service is not deployed.
- `.github/workflows/ci.yml`: one comment above the Run it step (it said no answers were recorded). No
  step, permission or secret changed.
- `tests/test_runit.py`: `ShippedRecordingsTest`: every sample in the manifest has a recording that the
  recording workflow's own check (`runit check-recording`) lets through, from a numbered run.

## What was run
- `run-it.yml` dispatched by hand on main (ccc54d5), once per sample; no model and no secret. Conclusion
  and jobs read from the API: each run `success`, jobs `verify` and `publish` both `success`.
  - [43514147344](https://github.com/Expectrail/Expectrail/actions/runs/43514147344), `clean`: accept,
    as expected; 120 of 120 vision questions answered from the recording.
  - [43514430601](https://github.com/Expectrail/Expectrail/actions/runs/43514430601), `fall-through-repair`:
    accept, as expected; 135 of 135.
  - [43514715045](https://github.com/Expectrail/Expectrail/actions/runs/43514715045), `fall-through-bug`:
    reject, as expected; 135 of 135.
  The folders are on `run-it-results` under `builder1-recorded-clean`, `builder1-recorded-repair` and
  `builder1-recorded-bug`.
- CI on main at ccc54d5, [run 43513054013](https://github.com/Expectrail/Expectrail/actions/runs/43513054013),
  conclusion `success`, job `seeded-bugs`: the offline Run it step printed accept, reject, accept, each
  "vision answers recorded on 2026-11-13".
- `python3 -m unittest tests.test_capabilities tests.test_runit tests.test_runit_links`: 78 tests, OK.
- The full suite: see the pull request.
- The live page was not looked at: this session's proxy refused expectrail.tech. The page is not
  changed here.

## Not done
- Visitors still cannot start a run: the service's account, token, secret and DNS are Sean's steps
  (`docs/run-it.md`). Then the burst against the deployed function and the first visitor run.

## Files
- `docs/run-it.md`
- `docs/capabilities.json`
- `docs/capabilities.md`
- `.github/workflows/ci.yml`
- `tests/test_runit.py`
- `docs/new-work/2026-11-13-run-it-recorded-samples.md`
