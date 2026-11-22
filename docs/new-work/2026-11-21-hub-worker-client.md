# Worker cookie format and GitHub client

## What changed

Port the session format and the OAuth exchange, identity and scoped repository listing for the hub Worker. The offline fixture gives different users different grants.

## What was run

The unsigned-cookie test first failed to import the missing implementation. The pull request records the Node and full Python runs.

## Files

`apps/hub-edge/` contains the session and GitHub modules, Node package declaration, fixture and tests.

## Not done

The Worker entry point, request handlers, deployment guide and durable store are separate changes. No live sign-in was attempted.
