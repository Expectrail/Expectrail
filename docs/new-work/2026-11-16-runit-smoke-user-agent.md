# The Run it smoke check names its client, so Cloudflare lets it through (#265)

## What changed
During the first deploy of Run it to api.expectrail.tech, the closed smoke check failed at `health`
with a ValueError: Cloudflare's browser integrity check answered Python's default `Python-urllib`
agent with error 1010, while a browser got the right health JSON. `tools/runit_api_smoke.py` now
sends `User-Agent: expectrail-runit-smoke/1 (+https://expectrail.tech)`.

## What was run
- With this agent, against https://api.expectrail.tech (deployed version 95dbff30), Sean ran the closed
  check on November 16: all five lines passed (health, disallowed origin, RUN_IT_OPEN closed, no
  sample start, no progress poll).
- Full suite on the branch: 4548 tests OK (52 skipped).

## Not done
The open check (`--expect-open true`) waits for section D of docs/run-it-deploy.md.

## Files
- tools/runit_api_smoke.py
- tests/test_runit_api_smoke.py
- docs/new-work/2026-11-16-runit-smoke-user-agent.md
