# A repair record's folder may be reached through a link; its proofs may not (#378)

## What changed
#611 runs CI's `test` job with `TMPDIR` behind a link, as every temporary folder is on macOS. On main
with #581 that turned the job red: `repair_provenance.provider_only` refused an invocation proof
whenever *any* folder above it was a link (`target.resolve() != target.absolute()`), so a repair
record in a temporary folder could never be published (`tests.test_433_remaining`, run
44226903588). `tools/ci_autofix.py` had the same check.

Both now use one helper, `expectrail.gate.record.unlinked_below(base, relative)`:
- links above the record's own folder are allowed;
- every component of the proof's path below that folder must not be a link, and the path may not be
  absolute or contain `..`;
- as a fallback for anything the walk misses, the resolved path must equal the resolved folder
  joined with the relative path.

Reading the proof still goes through `read_bytes_capped`, which opens with `O_NOFOLLOW`. So a
linked proof, or a linked attempt folder, is still refused, with the same message as before.

## What was run
- `TMPDIR=<a link> python3 -m unittest tests.test_433_remaining` on main f167f4e before the change:
  1 error, `linked invocation proof` (the CI failure, reproduced).
- The same with the change, plus `tests.test_linked_proof`: 16 tests, OK.
- The full suite with `TMPDIR` behind a link, as CI's `test` job runs it, on main f167f4e plus the
  change: 4882 tests, `OK (skipped=64)`.
- After #615 merged: this branch merged with main 626753b, plus #611 brought back (a revert of the
  revert ae40ef3), with `TMPDIR` behind a link: 4908 tests, `OK (skipped=64)`.

## Not done
The guard's revert of #611 (#615) merged first. This branch brings #611's change back (CI's linked
`TMPDIR`, `tests/test_linked_paths.py` and #611's own work-log file) together with this fix.

## Files
- `expectrail/gate/record.py` (`unlinked_below`)
- `expectrail/repair_provenance.py`
- `tools/ci_autofix.py`
- `tests/test_linked_proof.py`
- `docs/new-work/2026-11-18-linked-proof-folder.md`
