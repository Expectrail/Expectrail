# trust-check takes a GitHub attestation in place of a trust-store key (#255)

## What changed
`expectrail trust-check` (and `python -m expectrail.receipt trust-check`) takes
`--attested-by OWNER/NAME/.github/workflows/FILE.yml` in place of `--trust-store`, with `--repo` required and
`--source-ref` and `--bundle` optional. The issuer is then the workflow that attested the receipt file: the
command runs `expectrail.attestation`'s check (`gh attestation verify` with every pin, then each pin again on
gh's JSON) and reads no trust store.

- The issuer is known only when that check verified this file's exact bytes for the asked repository. The
  receipt is parsed from the same bytes, and a file that changes while it is read checks nothing.
- The receipt's own signature must still verify, with the key it carries. The attestation vouches for the
  bytes. It does not make up for a signature that fails inside them.
- Every other clearance condition is unchanged: repository, head, build and policy asked and matched,
  freshness, completeness and decision accept.
- Exactly one of `--trust-store` and `--attested-by`. A command line that mixes them, or that the
  attestation check cannot use, checks nothing and never calls gh.
- The report says `issuer: attested (by WORKFLOW at REF)` or `issuer: NOT ATTESTED (...)`, with gh's reasons.

The ledger row `verifier-receipts` now lists the attestation path and its limits. Its "installed trust-check
remains a placeholder" (and the same sentence in `installed-command`) is no longer true: `expectrail trust-check`
runs this module's check. Both sentences are corrected.

Stacked on #547 (the attestation module).

## What was run
- `python3 -m unittest tests.test_trust_check_attested`: 15 tests, OK. This covers the in-process command,
  `expectrail trust-check` through `expectrail.cli`, the library call, and a process with a stand-in `gh` on
  the PATH.
- Five mutations of the new code, each caught: the attested test removed (9 failures), the file digest test
  removed (2), the repository test removed (2), the receipt's own signature taken as valid (1), and the
  one-issuer rule removed (1 failure, 1 error).
- `python3 -m expectrail.capabilities check`: no problem.
- Full suite: see the pull request.

## Not done
- No workflow attests a receipt yet. That needs `id-token: write` and `attestations: write`, which are Sean's,
  in the trusted job #254's session owns. So gh's output in these tests is written by the tests.
- The Verify a receipt page cannot run gh. It checks trust-store receipts only.

## Files
- `expectrail/receipt.py`, `expectrail/cli.py`
- `tests/test_trust_check_attested.py`
- `docs/receipt-attestation.md`, `docs/capabilities.json`, `docs/capabilities.md`
- `docs/new-work/2026-11-16-trust-check-attested.md`
