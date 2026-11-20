# Run it's calls to GitHub use a redirect mode Cloudflare accepts (#265)

## What changed
The first open check on the deployed service (November 17, 01:32 CT) reserved a run
(1e73a5c4-b7f4-4e55-b91e-efeb046b0f38), but GitHub never started one. The Worker passed
`redirect: "error"` to `fetch`, which Node accepts but Cloudflare Workers do not (only `follow` or
`manual`), so every call to GitHub threw before it was sent. The service read that as an unclear
dispatch and kept the reservation. The token itself was fine: a read of the workflow with it gave HTTP 200.
`apps/run-it-edge/service.js` now uses `redirect: "manual"`. A redirect is never followed: a redirected
dispatch is a refusal (nothing started or counted), and `read()` still requires 200.

## What was run
- `node --test apps/run-it-edge/test/service.test.mjs`: 25 pass. The deadline test now requires a
  value Workers accept, and a new test refuses a 302 on dispatch.
- Full suite: see the pull request.

## Not done
The live Worker must be updated from this code, and the open check rerun. The tests still run on
Node, not on Workers' runtime; this class of mismatch is only caught on the deployed service.

## Files
- apps/run-it-edge/service.js
- apps/run-it-edge/test/service.test.mjs
- docs/new-work/2026-11-17-runit-redirect-manual.md
