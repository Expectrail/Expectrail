# Port hub sign-in to a separate Worker

## What changed

Port the Python sign-in and cookie handlers to the hub Worker and use the domain store interface agreed on #785. SQLite storage belongs to #786.

## What was run

On the full service tree, Node passed 16 tests and Python ran 5,956 tests in 627.682 seconds, OK with 79 skipped. The two Python reference modules passed all 47 tests. A local Chromium rehearsal completed sign-in, repository listing and sign-out with a loopback authorization redirect. An earlier browser rehearsal timed out waiting for the redirect. The portable Node service tests use an injected transport.

The integration rehearsal combined service `ff63ca1c`, client `d0558abb` (#789) and store `8f3c081a` (#791). All 23 Node tests passed. Wrangler 4.166.0 listed `env.HUB (HubSessions)` and exited at `deploy --dry-run`. With a test storage backend and the real exported Worker and HubSessions class, a sign-in survived reconstruction, replay of its callback was refused, and sign-out revoked access.

Full Python discovery with the assets staged initially errored in `FolderTest.test_no_credential_is_in_the_folder` while decoding a binary font. The check now searches every file as bytes and names only the file on a match. With the fonts still in place, all five focused Python hub-edge tests passed and full discovery ran 5,962 tests in 618.571 seconds, OK with 79 skipped.

## Files

- `apps/hub-edge/`: Worker bindings, config example, service, GitHub client, signed cookies and offline tests.
- `docs/hub-deploy.md`: deployment and smoke checks for the operator.
- `tests/test_hub_edge.py` scans binary and text assets for the same credential patterns.
- This work log.

## Not done

Deployment, account configuration and live OAuth are Sean’s steps. Connected run evidence belongs to #713.
