# Run it, slice 3: the edge function, its quotas and a scripted burst (#265)

## What changed
- `apps/run-it-edge/service.js`: the edge function the page calls at `https://api.expectrail.tech`,
  speaking `expectrail.run-it-api/v1` (`/health`, `/run`, `/status/<id>`, and the stub's `/api/...`).
  Web-standard APIs only; storage, clock and fetch passed in. It accepts only `{"sample": id}` from
  the page's origin with one of the three sample ids, mints the request id, dispatches `run-it.yml` on
  main and reads its runs, and calls nothing else. Limits: one run at a time (busy), 3 per visitor a
  day (salted SHA-256 of the address, never the address), 40 a day, a circuit breaker after 3 failed
  runs in a row (closed by a person changing `BREAKER_EPOCH`), a run lost after 5 minutes or still
  going after 30 is failed, status reads cached 10 seconds. Closed unless `RUN_IT_OPEN` is `true` and
  every setting is valid. Requests are handled one at a time, so a burst cannot slip two runs between
  awaits.
- `apps/run-it-edge/worker.js` and `wrangler.toml.example`: a Workers-style adapter with one Durable
  Object, and an example configuration with no secret. `local.mjs`: the function on 127.0.0.1 with a
  pretend GitHub, for the burst script.
- `tools/runit_burst.py`: a scripted burst against the stub, the local function or the deployed one;
  fails on two accepted runs, an answer outside the contract, or a refusal that names no limit.
- Contract: `expectrail.run-it-api/v1` gains the refusal reason `unavailable` (GitHub could not be
  reached; nothing started, nothing counted). Writer: the edge function. Reader: the page, which has a
  line for it.
- `run-it.yml`: `run-name: Run it ${{ inputs.request_id }}`, which is how the function finds its run.
- `tools/runit_stub.py`: a listen queue of 128 instead of 5. The burst script found that the stub
  reset connections when 40 arrived at once.
- `docs/run-it.md`: the edge function, the burst, and Sean's list (host and account, the token's exact
  permission, the two secrets, DNS).

## What was run
- `node --test apps/run-it-edge/test/service.test.mjs` (Node 22.23.4): 16 tests, 0 failed. They
  include a burst of 200 at once (1 accepted, 199 busy, 1 dispatch) and 120 rounds of 30 at once from
  12 visitors with runs finishing (never two runs on GitHub, 36 dispatches: 12 visitors x 3).
- `python3 -m unittest tests.test_runit_edge tests.test_runit_site tests.test_runit`: 57 tests, OK.
  `tests/test_runit_edge.py` runs the Node tests and checks every body they produced (over 500)
  against the schema, and bursts 60 at the local function (1 accepted, 59 busy) and 40 at the stub
  (1 accepted, 39 busy).
- Looked at in Chromium (Playwright) at 1280x900 and 390x844: the page against the stub with the start
  request answered by an `unavailable` refusal. It showed "Run it could not start a run just now."
  with the service's sentence and "No earlier run of this sample is published yet."; no horizontal
  scroll at either width.
- The full suite: see the pull request description.
- Not run: `worker.js` on Cloudflare or any other host, and any call to GitHub. No account, token or
  model was used.

## Not done
- Sean's part: the host account, the token, the secrets, DNS (docs/run-it.md, "What Sean does").
- A burst against the deployed function, once it exists.
- The nightly platform test exercising this path.

## Files
- `apps/run-it-edge/service.js`, `worker.js`, `local.mjs`, `package.json`, `wrangler.toml.example`,
  `test/service.test.mjs`
- `tools/runit_burst.py`, `tools/runit_stub.py`, `.gitignore`
- `contracts/run-it-api.v1.schema.json`, `docs/run-it/run-it.js`, `.github/workflows/run-it.yml`
- `docs/run-it.md`, `tests/test_runit_edge.py`, `docs/new-work/2026-11-13-run-it-edge.md`
