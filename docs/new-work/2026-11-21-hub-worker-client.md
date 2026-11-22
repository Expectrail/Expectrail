# Worker cookie format and GitHub client

## What changed

Port the session format and the OAuth exchange, identity and scoped repository listing for the hub Worker. The offline fixture gives different users different grants.

The merge guard found that the JavaScript tests ran nowhere: no required check executed `node --test` in `apps/hub-edge`, so the cookie verifier and the GitHub client could have been broken by a later change with every check still green (#789 review, 2026-11-22). `tests/test_hub_edge.py` closes that. It globs `apps/hub-edge/test/*.test.mjs`, so each later hub-edge slice joins the required `test` job by being written rather than by remembering to wire it up, and it checks that the JavaScript signer and `hub/session.py` still agree byte for byte in both directions.

## What was run

The unsigned-cookie test first failed to import the missing implementation. The pull request records the Node and full Python runs.

`python3 -m unittest tests.test_hub_edge` ran 5 tests, OK (Node v22.23.4). Two mutations were made and both were caught: inverting an assertion in `apps/hub-edge/test/session.test.mjs` failed `test_every_javascript_test_passes`, and changing the signer's domain prefix from `expectrail-hub/v1` to `/v2` failed `test_the_javascript_signer_and_hub_session_agree`. The suite passed again once both were reverted.

## Files

`apps/hub-edge/` contains the session and GitHub modules, Node package declaration, fixture and tests. `tests/test_hub_edge.py` runs those tests inside the required `test` job and fails, rather than skips, when Node is missing in CI.

## Not done

The Worker entry point, request handlers, deployment guide and durable store are separate changes. No live sign-in was attempted.
