# Evidence storage (#566)

## What changed

Added the main/evidence-branch rule and a 256 KiB PR limit for new or replaced
non-manifest files under docs. Named fixture exemptions must already be reviewed
on the PR base. The existing unittest discovery runs the limit and link checks;
no workflow changed.

Added manifest and exemption schemas/examples plus a local preparation tool and
reader. Preparation verifies a standalone Git bundle before removing raw files.
The reader reports missing, changed and unexpected files. Symlinks and unsafe
paths are refused. Evidence is pinned to a commit, never to a moving branch tip.

Moved the merged Breakout menu trial's 42 raw files (474,350 bytes) into evidence
commit `3c9dcaeb55a35f4dceb7eb7e8276ab43997cf313`, prepared as a separate bundle.
The manifest/index and the report's links remain on main. Every byte was checked
against source main commit `d36c8063449afe6c4113c74d0ff39e926b861b6c`.
No tests, dossier code or capability ledger entries read the moved folder.
Trial summaries, inputs, selection, command log and screenshot remain on main.
No evidence commit has been pushed, and no main-branch commit was made.

## What was run

- Required historic-base fetch, then full unittest discovery before changes:
  4,453 tests, 55 skips, no failures or errors, 491.230 test seconds.
- `python3 -m unittest tests.test_evidence_storage tests.test_schema_pattern -v`:
  30 tests passed (20 new evidence tests and 10 existing schema-pattern tests).
  One test imports with NumPy and Pillow unavailable.
- The first full after-run found one missing schema-pattern sample-table update
  (4,471 tests, 1 failure, 55 skips). Added five sample strings; existing
  assertions are unchanged. The final rerun is recorded separately.
- Bundle verification, local fetch, all 42 source hashes and archived hashes,
  and all manifest-backed docs links: passed. Bundle is self-contained.
- Export scan before changes: 749 files, no errors or warnings.
- Final full discovery: 4,473 tests, 55 skips, no failures or errors,
  508.382 test seconds. Before/final failing-test name lists are both empty.
  Intermediate and final logs and the name comparison are in the handover.
- Final export scan: 712 files, no errors or warnings.
- Patch application checked against the named base using a separate Git index;
  the resulting tree equals the delivered tree.

## Not done

No GitHub writes, pushes, workflow edits, live models or spend. Sean must publish
the evidence branch before the main PR so its immutable links become public.

At the base commit, #556 and #559 are open. The pointer/menu evidence and later
Breakout retrial folders are not on main, so they were not imported or migrated.
The handover gives follow-up steps for those folders after their PRs merge.
This is Part of #566; it does not close the remaining migrations.

## Files

- `docs/evidence-storage.md`, `docs/evidence-exemptions.json`: rule and empty
  reviewed-exemption list.
- `contracts/evidence-manifest.v1.schema.json`,
  `contracts/evidence-exemptions.v1.schema.json`, and their examples.
- `tools/evidence_storage.py`, its `.gitignore` allowlist entry, and
  `tests/test_evidence_storage.py`; five new entries in the existing
  `tests/test_schema_pattern.py` sample table.
- `docs/outside-trials/breakout/evidence/`: raw files replaced by a manifest/index.
- `docs/outside-trials/breakout/report.md`, `issues.md` and `commands.md`:
  evidence links/header retargeted; findings and recorded commands unchanged.
- This work log. The handover includes the full file list and separate bundle.
