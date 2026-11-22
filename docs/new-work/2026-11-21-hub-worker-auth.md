# Port hub sign-in to a separate Worker

## What changed

Port the Python sign-in and cookie handlers to the hub Worker and use the domain store interface agreed on #785. SQLite storage belongs to #786.

## What was run

On the full service tree, Node passed 16 tests and Python ran 5,956 tests in 627.682 seconds, OK with 79 skipped. The two Python reference modules passed all 47 tests. A local Chromium rehearsal completed sign-in, repository listing and sign-out with a loopback authorization redirect. An earlier browser rehearsal timed out waiting for the redirect. The portable Node service tests use an injected transport.

## Files

- `apps/hub-edge/`: Worker bindings, config example, service, GitHub client, signed cookies and offline tests.
- `docs/hub-deploy.md`: deployment and smoke checks for the operator.
- This work log.

## Not done

Deployment, account configuration and live OAuth are Sean’s steps. Connected run evidence belongs to #713.
