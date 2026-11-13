# The Run it page, against a local stub of the edge function (#265, slice 2)

## What changed
- `docs/run-it/index.html` and `docs/run-it/run-it.js`: the Run it page. It lists the samples from
  `samples.json`, starts a run through the service, follows its phases, and shows the published
  folder: the verdict from `status.json` (only an accept with every vision question answered from the
  recording is green; a failed, cancelled or unreadable result is never success), "vision answers
  recorded on <date>" or that none are recorded, whether the run ended as the sample is expected to,
  the receipt ("not signed yet (#255)"), and the evidence viewer's one-file export in a frame sandboxed
  with `allow-scripts` only. Refusals (busy, quota, daily cap, circuit breaker, switched off, service
  unreachable) say which and when they reset, and show the latest finished run of the sample, labelled
  earlier with its time. Text from the service or a result is never written as HTML.
- `contracts/run-it-api.v1.schema.json` with two examples: the service's bodies (health, accepted,
  refused, status). Writer: `tools/runit_stub.py` (and slice 3's edge function). Reader: the page; the
  stub's tests check every body against the schema.
- `contracts/run-it-latest.v1.schema.json` with an example: `latest.json` on the results branch, the
  latest run of each sample, an index only. Writer: `expectrail/runit_site.py` (`update_latest`,
  `python -m expectrail.runit_site latest`), called by the publish job in `run-it.yml` after the check
  and by the stub. Reader: the page.
- `tools/runit_stub.py`: the local stand-in for the edge function, on 127.0.0.1 only. It runs the
  sample (real runs, or stand-in replays with `--stand-in`), runs main's `expectrail.runit check`,
  publishes only a folder that passes, updates `latest.json`, and holds the limits: one run at a time,
  per visitor per day (salted hash of the address), a daily cap, a circuit breaker. `.gitignore` names
  it, as `tools/` is ignored except the files it names.
- `docs/run-it.md`: the page, the contract and the stub.

## What was run
- `python3 -m unittest tests.test_runit_site tests.test_runit tests.test_schema_pattern`: 57 tests, OK.
  `tests/test_runit_site.py` (21 tests) drives the stub's real HTTP server with the stand-in replays
  through the real `runit run`, gate, viewer and `runit check`. No Godot and no model ran.
- The full suite on this branch merged with main: see the pull request for the count.
- The page in Chromium (Playwright), against the stub with `--stand-in --stand-in-recorded`, at
  1280x900 and 390x844: a run of `fall-through-bug` showed the phases, then "Rejected" with the
  vision line, the facts and the viewer rendering in its sandboxed frame (its inspector's scripts ran);
  `clean` showed "Accepted" in green. Against the stub with no recordings, `clean` showed "Needs
  review" with "no vision answers are recorded". With `--per-visitor 1`, a second run showed the quota
  refusal with its reset time and the latest run labelled "Earlier run, from <time>". With `--closed`,
  at phone width, the service line said Run it is not starting runs and every Run it button was
  disabled. No console errors after the first run (before one, `latest.json` is a 404, as expected).
  These were stand-in replays, not the game.

## Not done
- The edge function (slice 3) and its burst test; the page calls `https://api.expectrail.tech`,
  which does not exist until Sean creates the account, the token and DNS. Until then the page on
  expectrail.tech says the service is not reachable and lists the latest runs (none yet).
- The home page does not link to Run it yet; that waits for the first visitor run on the domain.
- No real (Godot) run went through the stub here: no Godot on this machine.

## Files
`docs/run-it/index.html`, `docs/run-it/run-it.js`, `docs/run-it.md`, `contracts/run-it-api.v1.schema.json`,
`contracts/run-it-latest.v1.schema.json`, `contracts/examples/run-it-api-status.json`,
`contracts/examples/run-it-api-refused.json`, `contracts/examples/run-it-latest.json`,
`expectrail/runit_site.py`, `tools/runit_stub.py`, `.gitignore`, `.github/workflows/run-it.yml`,
`tests/test_runit_site.py`, `tests/test_package.py` (one name added to `NOT_PACKAGED`), `docs/new-work/2026-11-13-run-it-page.md`.
