# Trust store v2: retire and revoke issuer keys, and where the store is published (#255)

## What changed
- `expectrail.trust-store/v2` (`contracts/trust-store.v2.schema.json`, example
  `contracts/examples/trust-store.v2.json` with three throwaway keys). Each key has `validFrom`, an
  optional `notAfter` (retired: receipts it says it issued at or after are refused) and an optional
  `revoked: {at, reason}` (every receipt it signed is refused, whatever date it carries).
- `expectrail/receipt.py`: `parse_trust_store` reads v1 and v2 and returns `TrustKey` entries.
  `check_receipt` makes a v2 key a known issuer only when it is not revoked and the receipt's
  `issuedAt` (RFC 3339 with an offset) is inside its span. A store built in code with plain public-key
  strings still works as v1.
- A field a reader does not know now refuses the whole store, in v1 too: a v1 key entry may hold only
  `id`, `publicKey` and `note`. Before, a v1 entry's extra fields were ignored, so a `revoked` written
  into a v1 store would have been read past and the key trusted.
- `python -m expectrail.receipt trust-store show|add|retire|revoke STORE ...` edits a v2 store's public
  material. It writes atomically, only what the reader accepts, and prints the file's SHA-256. It
  refuses a reused id or public key, a non-canonical key, a second retirement or revocation, an empty
  span and any edit of a v1 store, and leaves the file unchanged when it refuses.
- The Verify page (`docs/verify/receipt-check.js`) reads v2 with the same rules and the same reason
  lines. The page's trust store hint links the new doc.
- trust-check's report and the Verify page no longer say more than was decided when the signature
  was not checked: the identity line said "mismatch" / "does not match" whenever the signature was
  not valid, even when every digest asked for matched; it now says "not shown (no valid signature
  from a trusted key)" unless a digest really differs. The issuer line says a revoked key, or a key
  outside its dates, is in the trust store and why it is not trusted, instead of "UNKNOWN" / "not in
  your trust store".
- After the merge guard's review: both readers refuse a store that lists one `publicKey` under more
  than one id, in v1 and v2, with the same reason line ("trust store lists one publicKey under more
  than one id: A and B"). Before, a key revoked under one id still cleared under another. As a
  fallback for a store built in code that never went through the reader, `check_receipt` (and the
  page's `checkReceipt`) refuses a key when any entry with the same public key is revoked.
- `docs/trust-store.md`: the two formats, where Expectrail's store will be published
  (`trust/expectrail.json`, by reviewed pull request, checked by tag and SHA-256, never taken from
  where the receipt came from), and the rotation and leaked-key steps.

## What was run
- `python3 -m unittest tests.test_trust_store_rotation`: 19 tests, OK. They cover a retired key
  before, at and after `notAfter`; a new key before and after `validFrom`; a retired key's receipt
  expiring 7 days after; a revoked key at three dates; `issuedAt` with no offset, an impossible date or
  junk; 21 stores that must be refused whole (also through the schema for the 9 shape cases); trust-check
  as a process (exit 0, 1 with the revocation reason, 2 for a v1 key carrying `revoked`); a rotation
  made with the editing commands; each refusal leaving the file unchanged; and the page against
  trust-check on 34 cases, field for field, under Node.
- Five mutations were each caught: the page's revocation check removed (3 failures), `issuedAt <
  notAfter` changed to `<=` in Python (2), the page's unknown-field refusal removed (4), Python's
  unknown-field refusal removed (7), Python's span check removed (13).
- `python3 -m unittest tests.test_receipt tests.test_verify_receipt_page`: 38 tests, OK.
- `tests.test_trust_store_rotation.PageWordsInBrowserTest`: the page in Chromium at 390 px with a
  revoked key: "in your trust store, and revoked", identity "not shown", no "does not match". Removing
  the page's revoked wording fails it.
- Looked at the Verify page in Chromium at 1280 px and 390 px with a revoked v2 key: the result card
  reads No clearance, the revocation reason is listed, the layout holds at phone width.
- After the review: `python3 -m unittest tests.test_trust_store_rotation tests.test_verify_receipt_page`:
  28 tests, OK. New: the guard's probe (K revoked as `old`, the same K as `alias`) refused with the
  reason line; the code-built-store fallback, in both orders; three duplicate-key stores in the
  refused-whole list and in the page/trust-check agreement test, with the page's message checked.
  Mutations: Python's duplicate refusal removed (7 failures), Python's fallback removed (2), the
  page's duplicate refusal removed (4). The page's fallback is not reachable through its public
  `check()` (stores always go through its reader), so it has no test of its own.
- Full suite on the branch merged with main: see the pull request.

## Not done
- No Expectrail issuer key exists, so `trust/expectrail.json` is not created. Creating the key and
  storing its signing half are Sean's.
- CI attestation (`id-token: write`, `attestations: write`) and writing the receipt from the trusted
  job are unchanged.
- No `expectrail trust-store` on the installed front door; the module command is the way in.

## Files
- `contracts/trust-store.v2.schema.json`, `contracts/examples/trust-store.v2.json`
- `expectrail/receipt.py`
- `docs/verify/receipt-check.js`, `docs/verify/verify.js`, `docs/verify/index.html`
- `docs/trust-store.md`
- `tests/test_trust_store_rotation.py`
- `docs/new-work/2026-11-16-trust-store-rotation.md`
