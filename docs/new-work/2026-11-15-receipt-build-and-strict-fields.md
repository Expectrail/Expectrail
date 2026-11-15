# Receipts: a build expectation, strict base64 and checked timestamps (#255)

## What changed
The three gaps the merge guard found in its review of #477, closed in `trust-check` and in the browser
check on `docs/verify/` alike, so the two readers still give the same report.

- **A substituted build.** `trust-check` takes `--expect-build DIGEST` (`check_receipt(expect_build=...)`),
  and clearance needs it, like the head. A genuine receipt for build X of a head and policy gets no
  clearance when presented for build Y ("build digest mismatch", "build identity"). Leaving it out is
  "build not checked", never a pass. The Verify page has a "Build digest you expect" field, its
  test samples fill it, and the command it prints carries `--expect-build`.
- **Timestamps on write.** `write_receipt` refuses an `issuedAt` or `expiresAt` that is not an RFC 3339
  date-time with an offset (`Z` or `+hh:mm`) naming a real date and time. jsonschema does not enforce
  `format: date-time` by itself, so the writer checks it (`check_timestamp`). It accepted
  `"yesterday"` before. The reader is unchanged: a receipt signed outside the writer with a bad
  timestamp still reads, and still gets no clearance ("unparseable timestamps").
- **One spelling for the signature and the keys.** The signature must be canonical base64 of 64 bytes
  and each public key canonical base64 of 32 bytes: padded, nothing outside the alphabet, the unused
  bits of the last character zero, and no trailing newline (matched with `fullmatch`, because a
  jsonschema `pattern` lets `$` match before one). The schema carries the patterns, `read_receipt` and
  `parse_trust_store` refuse anything else (trust-check exits 2), and `verify_signature` decodes with
  `validate=True` and a re-encode check as the fallback. Junk appended to a valid signature verified
  before. The page applies the same expressions and says "not a receipt this page can read" where
  trust-check exits 2; it used to say "cannot tell" for these. Its base64 decoder keeps a
  re-encode check as the fallback.
- `parse_trust_store(text)` is the trust store reader without a file; the page's parity test uses it
  in place of its own copy.

## What was run
- `python3 -m unittest tests.test_receipt tests.test_schema_pattern tests.test_verify_receipt_page`: OK
  (31 receipt tests, 7 of them new; 7 page tests, one of them in Chromium).
- New receipt tests: another build of the same head with a control that the named build clears; build
  not checked; the command with the right build (exit 0), another build (1) and none (1); the writer
  refusing 11 bad timestamp forms in each field and taking `Z`, offsets and fractions; 7 other
  spellings of a valid signature (junk, newlines, unpadded, URL-safe alphabet, padding bits set, a
  space) each refused by `read_receipt`, by `verify_signature` and by the command (exit 2); 5 other
  spellings of a key refused in the receipt and in the trust store.
- The page against `check_receipt()`, field for field: 7 new cases (another build, build not checked,
  a trust-store key in another spelling, an all-zero key, junk appended, padding bits set, a newline
  after the signature).
- Mutations, each caught: clearance without the build in the page (3 tests failed) and in Python (3);
  the page without its signature pattern (5); the writer without the timestamp check (11); the reader
  without its `fullmatch` on the signature (1).
- Looked at in Chromium at 1280 px and 390 px: the accept sample clears with the build filled in,
  changing the build to `fff…` shows "No clearance", "Build identity: does not match" and "build digest
  mismatch". No horizontal scroll at either width.
- Full suite on the branch (main at 137e003): 3,810 tests, OK, 39 skipped.

## Not done
- CI attestation (`actions/attest`, `id-token: write`, `attestations: write`): a human-only workflow
  change, and writing the receipt from the trusted CI job.
- A real CI receipt through `gh attestation verify` and `trust-check`, an Expectrail trust store and
  its rotation, and packaging `trust-check` as `expectrail trust-check`.
- The release gate rows "wrong build or head", "unknown signer" and "expired receipt" (#258) are still
  open: they wait on a receipt from a real run.

## Files
- `expectrail/receipt.py`
- `contracts/receipt.v1.schema.json`
- `docs/verify/receipt-check.js`, `docs/verify/verify.js`, `docs/verify/index.html`
- `tests/test_receipt.py`, `tests/test_verify_receipt_page.py`, `tests/test_schema_pattern.py`
- `docs/new-work/2026-11-15-receipt-build-and-strict-fields.md`
