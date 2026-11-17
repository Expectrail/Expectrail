# Run it is live on api.expectrail.tech (#265)

## What changed
Run it went from closed to open on the deployed service: a visitor on expectrail.tech/run-it/ can now start
a sample run and get a fresh result. This entry records the live evidence the deploy guide asks for
(step 78). No code changes.

## What was run (November 16 and 17, 2026; Sean, following docs/run-it-deploy.md)
- Deployed the Worker `expectrail-run-it` on Cloudflare with the custom domain api.expectrail.tech.
  First version 95dbff30 (November 16), then 93567b5a (November 17, with the fix from #595).
- Closed check, twice (before and after the secrets): all five PASS lines, zero start requests.
- The secrets `GITHUB_TOKEN` (fine-grained, Expectrail/Expectrail only, Actions read and write, expires
  December 17) and `VISITOR_SALT` were set only after #591 moved every model key into `spend`, so a
  run the token starts cannot spend without Sean's approval.
- First open check (version 95dbff30): the reservation was made, but no run started, because Workers
  refuse `redirect: "error"`. Fixed in #595 and redeployed.
- Open check on 93567b5a: health, origin, open and start PASS. The progress poll hit its 10-second
  request timeout while the service was answering (see Not done).
- Live runs, all on commit bf31c92e8f65 and all `success`:

| Request | Sample | Result | Run |
| --- | --- | --- | --- |
| 755e0c3f-55ca-4dd9-85e2-bca6de9b35c0 | fall-through-bug (open smoke check) | reject, as expected | [44133603903](https://github.com/Expectrail/Expectrail/actions/runs/44133603903) |
| 7cc775c6-9976-4733-b38f-86b68ede6727 | clean (Run button on the page) | accept, as expected | [44135389301](https://github.com/Expectrail/Expectrail/actions/runs/44135389301) |
| b4c22712-f750-455e-8009-87a1d008cce1 | fall-through-bug (Run button on the page) | reject, as expected | [44135877669](https://github.com/Expectrail/Expectrail/actions/runs/44135877669) |

- The service's status for 755e0c3f read `published`, and https://expectrail.tech/run-it/ showed b4c22712's
  result: rejected, vision answers labelled as recorded on 2026-11-13 (135 of 135 from the
  recording), receipt "not signed yet (#255)".

## Not done
- The smoke check's progress poll allows 10 seconds per request. A status refresh can make up to
  three GitHub reads in a row, so it can exceed that and report a timeout while the run is healthy.
- Receipts are not signed (#255). The recorded-fix card stays closed (`RECORDED_FIX_OPEN=false`).
- The Worker's tests run on Node, not on the Workers runtime (the cause of the redirect bug).

## Files
- docs/new-work/2026-11-17-runit-live.md
