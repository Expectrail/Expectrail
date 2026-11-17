# Run it nightly: check the deployed service daily and follow one run to what the page shows (#265)

## What changed
The Done-when line "the nightly platform test exercises the same path" needed a scheduled job on
the deployed service that keeps its output and follows the published result. `docs/run-it-deploy.md`
listed it as Sean's to arrange; it needs no secret and no new permission, so it is built here.

- `tools/runit_api_smoke.py --follow`: once a run is reserved, progress waits for the service to say
  `published` (not just `running`) and hands the run to `tools/runit_published.py`. Without
  `--follow` the smoke behaves as before.
- `tools/runit_published.py`: reads the published run from the address the page uses
  (`raw.githubusercontent.com/.../run-it-results`). `status.json` must match its schema, name this
  request and sample, have completed, decide the sample's expected decision, have answered every
  vision question from the recording, and agree with its own `asExpected`. An accept without
  recorded answers behind it fails. Then `findings.json` (a valid record, same decision), the
  evidence viewer (the viewer's page, with its Content-Security-Policy at the top) and
  `latest.json` (names this run or a later one). Raw content can lag, so a missing file or a stale
  index is waited for until a deadline, then it is a FAIL. Strict JSON: duplicate keys and NaN are
  refused. Size caps, no redirects, no credentials. Nothing read is run.
- `.github/workflows/run-it-nightly.yml`: daily at 09:17 UTC and by hand. `contents: read`, no
  secret, no environment, no model; actions pinned to commits. Closed check while the repository
  variable `RUN_IT_EXPECT_OPEN` is unset or `false`; when it is `true`, one recorded sample a day,
  rotating, followed to its published result. Output kept as the `run-it-nightly` artifact.
- `docs/run-it-deploy.md` and `docs/run-it.md` describe it. The ledger's `run-it` row lists the
  workflow and the two tools. `.gitignore` allows the new tool.

## What was run
- `python3 -m unittest tests.test_runit_published`: 23 tests, OK. The published files are made by
  the real `runit.run` on the stand-in replays with recordings from the scripted stand-in model,
  served from a dict and from a loopback HTTP server. No network, no GitHub, no model.
- Five mutations of the check (no recorded-vision check, no expected-decision check, no latest
  check, no CSP check, following on `running`), each caught by the tests; the first was caught only
  after adding a reject-without-recording case.
- The full suite on the branch merged with main: see the pull request.

## Not done
- The workflow has not run. It runs on main only after merge; nothing was dispatched from here.
- Not run against `https://api.expectrail.tech`. The deployed service's Cloudflare check refuses
  Python's default agent; #576 (not this change) gives the smoke its own `User-Agent`, and the
  nightly's `health` line fails until that is on main.
- Opening admissions and setting `RUN_IT_EXPECT_OPEN=true` are Sean's.
- The evidence viewer's headline is not compared with the decision here (the browser smoke does that).

## Files
- `.github/workflows/run-it-nightly.yml` (new)
- `tools/runit_published.py` (new)
- `tools/runit_api_smoke.py`
- `tests/test_runit_published.py` (new)
- `docs/run-it-deploy.md`, `docs/run-it.md`
- `docs/capabilities.json`, `docs/capabilities.md`
- `.gitignore`
- `docs/new-work/2026-11-17-runit-nightly.md`
