# The hub service's skeleton and GitHub sign-in against an offline stub (#712)

## What changed
A first code slice of the hub service, standard library only, with no credential in the repository.

- `hub/config.py`: every setting comes from the environment. With any sign-in setting missing or unusable (a short cookie key, a non-HTTPS origin), the service still starts and its pages say that GitHub sign-in is unconfigured, naming the missing settings, never their values.
- `hub/routes.py`: the route registry. A route module defines `register(registry)`; `hub.server` builds one registry per app and registers `hub.auth`, `hub.installations` and every `hub/runs*.py` module (#713's), so #713 never edits #712's files. Two modules cannot take the same route.
- `hub/session.py`: a signed cookie holding exactly a GitHub user id, login and expiry (one hour), and a separate ten-minute sign-in state cookie. The two are signed for different purposes, so one cannot stand in for the other.
- `hub/github.py`: the GitHub calls sign-in needs, through an injected transport. A list GitHub answers only in part is refused, never used as the whole.
- `hub/auth.py`: sign-in, the callback (state signed, unexpired, equal to the query's and used once), sign-out (POST from this hub's own origin only) and the projects page. The user token lives for the callback request only; the installations and repositories it shows are kept server side for the session's hour and refreshed at each sign-in.
- `hub/installations.py`: the setup return page, which trusts nothing in its query, and installation deliveries authenticated with the webhook secret. An uninstall or a removed repository disappears for every signed-in user at once.
- `hub/server.py`, `hub/__main__.py`: the WSGI app and `python3 -m hub`. Every response is `no-store` and carries a closed Content-Security-Policy.
- `tests/hub_stub.py`: the GitHub App and API stub and an in-process WSGI client. `tests/test_hub_auth.py` replaces `socket.socket` with a function that fails the test.
- `docs/hub-design.md`: a "Running the service" section with the settings and who creates each. `docs/assets/hub.css`: the account control in the header.

Found by looking in a browser: with `Referrer-Policy: no-referrer`, Chromium sends `Origin: null` on the sign-out form, and the origin check refused every real sign-out. The policy is now `same-origin`, and `Origin: null` stays refused.

Merge guard review: a cookie value the hub did not sign, with a non-ASCII character in it, raised out of `session.verify()` and gave a 500 on every page. `verify()` is now total: a value that is not base64url payload, a dot and a 43-character MAC is refused before the MAC is computed, and every decoding error returns None. An `installation` delivery with action `suspend` now hides that installation from signed-in users until they refresh from GitHub.

## What was run
- `python3 -m unittest tests.test_hub_auth tests.test_hub_runs_receipts`: OK.
- Eleven mutations of the checks (state comparison, one-use state, delivery signature, sign-out origin, uninstall for signed-in users, both incomplete-list checks, session expiry, signing out a session that lost its access record) were each caught.
- The pages in Chromium at 1280 px and 375 px against the stub: unconfigured, signed out, a full sign-in to the projects page, sign-out. No horizontal scroll.
- After the review: `HostileCookieTest` (16 hostile values, through `verify()` and through five routes, as session and as state cookie) and `SuspendTest`. On the earlier `session.py`, the hostile tests give 5 failures and 8 errors; with the fix, `tests.test_hub_auth` passes (41 tests).
- The full suite on the branch merged with main: see the pull request.

## Not done
- A durable store: this one is in memory, so a restart signs everyone out.
- Access is checked with GitHub at sign-in and then held for the hour; removals GitHub delivers apply at once, additions need a refresh.
- The hub's fonts are not served (the stylesheets fall back to system fonts).
- Nothing was run against github.com, and no GitHub App exists. Creating it, its secrets, the host, DNS and the privacy statement are Sean's.

## Files
`hub/__init__.py`, `hub/__main__.py`, `hub/config.py`, `hub/routes.py`, `hub/session.py`, `hub/store.py`, `hub/github.py`, `hub/web.py`, `hub/auth.py`, `hub/installations.py`, `hub/server.py`, `tests/hub_stub.py`, `tests/test_hub_auth.py`, `docs/hub-design.md`, `docs/assets/hub.css`, `docs/new-work/2026-11-21-hub-sign-in-skeleton.md`
