# A receipt's GitHub attestation: the predicate and the check (#255)

## What changed
- `expectrail.receipt-attestation/v1` (`contracts/receipt-attestation.v1.schema.json`, example
  `contracts/examples/receipt-attestation.v1.json`): the predicate the trusted job is meant to attest
  for each receipt file. Predicate type `https://expectrail.tech/attestation/receipt/v1`.
- `expectrail/attestation.py`: `predicate` (the writer) and `check` (the reader). `check` runs
  `gh attestation verify` with every pin, then checks gh's JSON again itself: the subject is the file's
  SHA-256, the predicate's copies equal the receipt's, the repository, signer workflow and ref, GitHub's
  OIDC issuer, GitHub-hosted runners. Anything it cannot read checks nothing (exit 2). It never says
  the receipt clears anything.
- `setup.py`: `attestation` is in the wheel, beside `receipt`.
- `docs/receipt-attestation.md`.
- No workflow changed: the attesting step needs `id-token: write` and `attestations: write` (Sean's).

## What was run
- `python3 -m unittest tests.test_attestation`: 17 tests, OK. They cover the example made by the
  writer; 22 pins that each refuse when they differ (predicate type, subject, the predicate's file
  digest, each of the 7 copied fields, an extra predicate field, repository, workflow, the same
  workflow path in another repository, the workflow file in another case, the signer's ref, the
  source ref, a self-hosted runner, the certificate issuer); five missing fields in gh's output; gh
  refusing; gh output that cannot be read; no gh; a receipt about another repository; a file changed
  while gh read it; and the module run as a process with a stand-in `gh` on the PATH (exit 0, 1, 2).
- Four mutations, each caught: the runner check removed (3 failures), the copied-field check removed
  (7), the source-ref check removed (1), the signer's ref check removed (1).
- `python -m expectrail.attestation check` on the example receipt with the real gh 2.89.0 here:
  "NOT VERIFIED", exit 1, gh's reason "no valid Sigstore verifiers could be initialized". No
  attestation exists for it, so that is the expected outcome; it shows a gh refusal is not a pass.
- Full suite on the branch merged with main: see the pull request.

## Not done
- The attesting step in CI (Sean: the permissions; #254's session: the trusted job).
- No real attestation has been checked: gh's output in the tests is written by the tests.
- `trust-check` does not yet accept an attestation in place of a trust-store key.

## Files
- `contracts/receipt-attestation.v1.schema.json`, `contracts/examples/receipt-attestation.v1.json`
- `expectrail/attestation.py`, `setup.py`
- `docs/receipt-attestation.md`
- `tests/test_attestation.py`
- `docs/new-work/2026-11-16-receipt-attestation-check.md`
