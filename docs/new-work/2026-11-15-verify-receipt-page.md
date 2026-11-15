# Verify a receipt in the browser, with trust-check's rules (#265)

## What changed
#265 asks for a site page that verifies a receipt ("run it, read evidence, verify a receipt, install")
and a visitor who "verifies its receipt". This adds `docs/verify/` (expectrail.tech/verify/):

- `receipt-check.js` checks an `expectrail.receipt/v1` file against an `expectrail.trust-store/v1` in
  the browser, line for line the same allow-list as `check_receipt()` in `expectrail/receipt.py`. Its
  report has the same fields, establishes, does-not-establish and reason lines.
- The signature is over Python's canonical JSON. The page has its own strict parser that keeps each
  number's text, refuses duplicate keys, NaN, Infinity and lone surrogates, and rebuilds the bytes as
  Python does: key order by code point, Python's string escapes, int against float, float repr.
- It fails closed. A timestamp outside RFC 3339, base64 that is not canonical, or a browser without
  Ed25519 gives "cannot tell" and a `trust-check` command, never a pass. A schema-invalid receipt gives
  "not a receipt this page can read", where trust-check exits 2.
- The page's policy has `connect-src 'self'`: a receipt or trust store you choose is never sent.
- Expectrail has no issuer key yet (#255), so two samples signed by a throwaway test key show it
  working, labelled as such. `python3 -m tools.make_receipt_samples` regenerates them with a fresh key
  and writes only the public half. The accept sample's validity ends 2026-11-22; after that the page
  shows "no clearance" for it, as it should.
- Run it's footer links the page.

## What was run
- `python3 -m unittest tests.test_verify_receipt_page`: 6 tests, OK. Node runs the page's check on 39
  receipts against `check_receipt()` (equal reports), 11 canonical-bytes cases (floats, astral and
  non-ASCII keys, escaped and raw), 2,000+ random doubles against `canonical_v1`, and the three
  cannot-tell forms. Chromium opens the page and checks what it shows.
- Mutations: replacing the float repr, the code-point sort, the policy term of clearance, or the
  7-day bound each made the tests fail (29, 4, 1 and 2 failures).
- `python3 -m agents.check_pages docs --offline`: 15 pages, 0 problems.
- Looked at in Chromium at 1280 and 390 px: no horizontal scroll; clearance green, reject red with
  its reasons.
- Full suite: see the pull request.

## Not done
- No real receipt: signing in CI and an Expectrail trust store wait on #255 (and a key, which is Sean's).
- Run it's result does not link a receipt yet, for the same reason.

## Files
- `docs/verify/index.html`, `docs/verify/receipt-check.js`, `docs/verify/verify.js`
- `docs/verify/samples/test-receipt-accept.json`, `test-receipt-reject.json`, `test-trust-store.json`
- `tools/make_receipt_samples.py`
- `tests/test_verify_receipt_page.py`
- `docs/run-it/index.html` (one footer link)
