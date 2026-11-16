# A receipt's GitHub attestation

A receipt (`expectrail.receipt/v1`) says what was checked and what was decided. Outside CI, who
issued it is shown by an Ed25519 signature from a key in a trust store you already hold
([trust-store.md](trust-store.md)). In CI, the trusted job is meant to also attest the receipt file
with a GitHub artifact attestation, so anyone can check which workflow wrote it, on which ref, without
holding a key. This page is that second path. Built so far: the predicate and the check. Not built:
the workflow step that makes an attestation (see "What is left").

## What is attested

- **Subject:** the receipt file, by the SHA-256 of its exact bytes.
- **Predicate type:** `https://expectrail.tech/attestation/receipt/v1`.
- **Predicate:** `expectrail.receipt-attestation/v1`
  ([schema](../contracts/receipt-attestation.v1.schema.json),
  [example](../contracts/examples/receipt-attestation.v1.json)): the file's digest and copies of the
  receipt's `repository`, `headSha256`, `buildSha256`, `policySha256`, `decision`, `issuedAt` and
  `expiresAt`. It is written by

  ```
  python -m expectrail.attestation predicate RECEIPT --out predicate.json
  ```

## Checking one

```
python -m expectrail.attestation check RECEIPT --repo OWNER/NAME \
    --signer-workflow OWNER/NAME/.github/workflows/FILE.yml [--source-ref refs/heads/main] [--bundle FILE]
```

It runs `gh attestation verify` with every pin (repository, signer workflow, source ref, predicate
type, GitHub's OIDC issuer, GitHub-hosted runners only). Then it reads gh's JSON and checks each pin
again itself, along with what gh does not check: a subject with this file's digest, and a predicate
whose copies match the receipt it sits beside. One result that passes every check is enough. A result
missing a field is refused, never skipped.

- Exit 0, `attestation: VERIFIED`: the named workflow, on the named ref, in the named repository,
  attested this exact file.
- Exit 1, `attestation: NOT VERIFIED`, with each reason: gh refused, or a pin differs, or the receipt
  is about another repository.
- Exit 2, nothing checked: gh is not installed, gh's output cannot be read, the receipt cannot be read
  or changed while it was read, or the command line is not usable. A signer workflow outside `--repo`
  (a reusable workflow) is not supported.

Owner and repository names are compared without case, as GitHub treats them. The workflow's path and
the ref are compared exactly.

**What it does not establish:** clearance. A verified attestation says who wrote the receipt, not that
it clears your change; that is `expectrail trust-check`'s question. The command says so in its output.

## What is left

- **The writer in CI** (Sean): the trusted job runs the `predicate` command and `actions/attest` with
  `subject-path` the receipt and `predicate-path` the predicate. That needs `id-token: write` and
  `attestations: write`, a person's change under `AGENTS.md`, and it sits in the job split #254's
  session owns.
- A real attestation checked with this command. Until then, gh's output in the tests is written by
  the tests, in the shape `gh attestation verify --format json` prints.
- Combining the two paths in `trust-check` (the attestation standing in for a trust-store key in CI).
