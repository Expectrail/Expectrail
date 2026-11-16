# The trust store: where it comes from and how keys rotate (#255)

A receipt (`expectrail.receipt/v1`) is signed with an issuer's Ed25519 key. `expectrail trust-check`
and the [Verify page](https://expectrail.tech/verify/) trust a signature only when the key is in a
**trust store the verifier already holds**. A key carried inside the receipt is never trusted on its
own. This page says how a verifier gets Expectrail's store, how to tell it is the right one, and how
the person who holds the keys changes them.

**Status, November 16, 2026.** The reader, the editing command and the Verify page support
everything below, tested offline with throwaway keys (`tests/test_trust_store_rotation.py`).
**Expectrail has no issuer key yet**, so there is no Expectrail trust store to publish. Creating the
key, and signing receipts in CI, are Sean's steps (see the end of this page). Nothing here has been
run with a real key.

## The two formats

| Format | Each key has | A key is trusted for |
| --- | --- | --- |
| `expectrail.trust-store/v1` | `id`, `publicKey`, optional `note` | any receipt it signed |
| `expectrail.trust-store/v2` | `id`, `publicKey`, `validFrom`, optional `notAfter`, optional `revoked: {at, reason}`, optional `note` | receipts it says it issued from `validFrom` (inclusive) to `notAfter` (exclusive), and none at all once `revoked` |

The schema is [`contracts/trust-store.v2.schema.json`](../contracts/trust-store.v2.schema.json) and
the example is [`contracts/examples/trust-store.v2.json`](../contracts/examples/trust-store.v2.json)
(three throwaway keys: one retired, one in use, one revoked).

Rules both readers keep (`expectrail/receipt.py` and `docs/verify/receipt-check.js`):

- **A field the reader does not know refuses the whole store.** That holds in v1 too: a v1 key
  with a `revoked` or `notAfter` is refused, not read as a plain key. Rotation needed a new format
  rather than new optional fields, because a reader that skipped a `revoked` it did not understand
  would go on trusting the key it was meant to stop trusting. A verifier from before v2 refuses a
  v2 store ("trust store must be expectrail.trust-store/v1") and checks nothing.
- **Dates are RFC 3339 with an offset**, and real dates. `notAfter` must be after `validFrom`.
- **Retired** (`notAfter`): the key is trusted for receipts it says it issued before `notAfter`. A
  receipt is valid for at most 7 days, so a retired key stops clearing anything 7 days after its
  `notAfter` at the latest. This is for a key that was replaced on schedule and whose private half
  was destroyed. The `issuedAt` it relies on is written by the signer, so it only means something
  while nobody else holds the key.
- **Revoked**: every receipt the key signed is refused, whatever `issuedAt` it carries, because
  whoever holds a stolen key can write any date. Use it whenever the private key may have been
  copied. Receipts it signed earlier stop clearing too: re-run those verifications under the new key.
- **A key not in the store** is "unknown issuer": no clearance. A verifier with an older copy of the
  store therefore refuses receipts from a new key. It fails closed, and the fix is a fresh copy.

What trust-check prints for each case:

```
issuer key revoked at 2026-10-20T09:30:00Z: the laptop that held it was lost
receipt issued outside the issuer key's validity (2026-10-01T00:00:00Z to 2026-11-01T00:00:00Z)
unknown issuer (key id not in trust store)
```

Each one leaves `issuer: UNKNOWN` and `clearance: no`.

## Where Expectrail's store will be published

Once Expectrail has a key, its store is one file in this repository, **`trust/expectrail.json`**
(`expectrail.trust-store/v2`), changed only by a pull request that Sean reviews and merges. Every
version is in the repository's history, so anyone can see when a key was added, retired or revoked.

A verifier gets it from a source that **does not come with the receipt**:

1. **The repository at a release tag.** `git show v<version>:trust/expectrail.json` from a clone, or
   the same path on GitHub at that tag.
2. **Its SHA-256.** `python -m expectrail.receipt trust-store show trust/expectrail.json` prints it.
   The release notes for each tag give the same digest, so a copy from anywhere else can be compared.
3. **The latest copy on main**, when a key was revoked after the last release. Compare its history
   with the release copy: the only difference should be the rotation.

Do not take a trust store from the same place as the receipt: whoever sends a forged receipt can
send a store that trusts their own key. The Verify page says this beside the trust store field, and
never loads a trust store by itself. It only fills in the throwaway test store for its samples.

The store is not shipped inside the wheel yet. While it holds no key there is nothing to ship, and a
copy inside an installed package would go stale silently after a revocation. Whether the release
workflow also attaches `trust/expectrail.json` with its digest to each release is a decision for
when the first key exists.

## Rotating a key (for the person who holds the keys)

`python -m expectrail.receipt trust-store` edits a v2 store's public material. It never sees a
private key. It reads its result back through the same reader trust-check uses and writes nothing
that reader would refuse. Each write prints the file's new SHA-256.

```
python -m expectrail.receipt trust-store show   STORE
python -m expectrail.receipt trust-store add    STORE --id ID --public-key BASE64 [--valid-from TIME]
python -m expectrail.receipt trust-store retire STORE --id ID [--at TIME]
python -m expectrail.receipt trust-store revoke STORE --id ID --reason TEXT [--at TIME]
```

`TIME` is RFC 3339 with an offset (`2026-12-01T00:00:00Z`); the default is now. Exit 0 when the store
was written, 2 when it was not (and it is then unchanged). It refuses: a second key with an id
already used, the same public key under a new id, a key that is not canonical base64 of 32 bytes, a
second retirement or revocation of one key, a `notAfter` that is not after `validFrom`, and any edit
of a v1 store.

`--public-key` must be the **public** half. A raw Ed25519 private key has the same length, so the
command cannot tell the two apart: check before you paste.

**A scheduled rotation** (say every 90 days):

1. Make the new key where the signer will use it. The private half never goes in a file in this
   repository, an issue, a log or an artifact.
2. `trust-store add trust/expectrail.json --id expectrail-YYYY-MM --public-key <new public key> --valid-from <switch time>`.
3. `trust-store retire trust/expectrail.json --id <old id> --at <switch time>`, the same time.
4. Open one pull request with the change and the printed digest. After it merges, switch the
   signer to the new key at the switch time.
5. Destroy the old private key. Its receipts keep verifying until they expire (7 days at most).

**A key that may have leaked:**

1. `trust-store revoke trust/expectrail.json --id <id> --reason "<what happened>"`.
2. Add a new key as above, with `--valid-from` now, and merge both in one pull request.
3. Re-run the verifications whose receipts must still clear: none signed by the revoked key will.

## What is left (Sean)

- **Create the first issuer key**, and decide where the signing half lives: a secret only the
  trusted job can read (a workflow change that adds a secret is a person's change under
  `AGENTS.md`). Then add its public half to `trust/expectrail.json` with the command above.
- **Sign receipts in CI**: the trusted job writes the receipt (#254's job split) and attests it,
  which needs `id-token: write` and `attestations: write`, also a person's change.
- Decide whether each release attaches the store and its digest.
