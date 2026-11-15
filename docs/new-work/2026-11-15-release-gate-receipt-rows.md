# The release gate's three receipt rows get real-process tests (#258)

## What changed
The rows "wrong build or head", "unknown signer" and "expired receipt" were open with "it needs the signed
receipt (#255)". The receipt verifier is on main (#477, #507), so each row now has tests in
`tests/release_gate/gate_receipt.py` that run `python3 -m expectrail.receipt trust-check` as its own
process against a trust store file and assert it does not give clearance (exit 1, "clearance: no", and
the reason it names).

The receipts come from two real `expectrail verify` jobs with Godot, made once for the class: the
unchanged game (accept) and the seeded bug (reject). Each receipt carries its job's head tree, request and
policy digests and its decision, and is signed with a key made in the test. The trusted job writes no
receipt yet (#255), so the rows' scope says the receipt writer and CI attestation are not covered.

- Wrong build or head: the unchanged game's receipt asked about the seeded bug's head; about another
  build (the bug job's request digest) of the same head; about another repository; with the head or the
  build left unasked.
- Unknown signer: signed by a key the store does not hold; the trusted key id with another key; the
  trusted public key with another key's signature; the seeded bug's honest reject, and the same receipt
  edited to accept after signing; a store that does not hold the signer's key.
- Expired receipt: past its expiry; issued in the future; valid for longer than 7 days; an expired
  receipt with its expiry moved after signing.

A positive control, the unchanged game's receipt asked about that job's own digests, is cleared by the
same command. It is the three rows' own baseline: without it they are not held.

## What was run
- `python3 -m unittest tests.release_gate.gate_receipt -v` with Godot: 14 tests, OK, 55 s.
- Seven mutations of `check_receipt` were each caught by these tests: the head comparison removed; the
  head, or the build, always counted as shown; any key id trusted; the signature not verified; the
  validity window ignored; the 7-day bound ignored.
- The release gate locally, with Godot and without bubblewrap (`python3 -m tools.release_gate --out
  docs/release-gate.md`), on 522ac07 with this change: 45 tests, OK, 6 skipped; held 21, open 9, failed 0,
  not run 5. The three receipt rows are held. The five not run need the replay sandbox.
- `python3 -m unittest tests.test_release_gate`: 21 tests, OK.
- The full suite merged with main at ec4c1f5: 4,114 tests, 1 failure, 26 skipped. The failure is
  `tests.test_recorded_renderer_drift.CaptureRendererTest.test_checked_in_recordings_match_the_capture_renderer`,
  and it fails the same way on unchanged main ec4c1f5 on this machine (Godot 4.7.2, llvmpipe): it compares
  the recordings with this machine's renderer. Main's CI run 43768135030 at ec4c1f5 concluded success.

## Also changed
`tools/release_gate.py` printed one line for all the rows' own positive controls, so with the two-job
controls skipped and the receipt control passed it said "NOT passed". Each set of a row's own controls
now gets its own line (`controls.ROW_BASELINE_GROUPS`), and `tests/test_release_gate.py` checks that the
receipt rows are read apart from the two-job rows.

## Not done
- The receipt written by the trusted job, and CI attestation (#255; the attestation permissions are
  Sean's).
- The local summary still has no bubblewrap here, so rows that need the replay sandbox are "not run" in
  `docs/release-gate.md`; CI's `release-gate` job has it.

## Files
- `tests/release_gate/gate_receipt.py` (new)
- `tests/release_gate/controls.py`
- `docs/release-gate.md` (regenerated)
- `tools/release_gate.py`
- `tests/test_release_gate.py`
- `docs/new-work/2026-11-15-release-gate-receipt-rows.md`
