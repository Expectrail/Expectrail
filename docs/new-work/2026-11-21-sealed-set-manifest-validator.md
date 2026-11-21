# The blind set's manifest format and a validator a person runs before sealing (#742)

## What changed
- New contract `expectrail.blind-manifest/v1`: `contracts/blind-manifest.v1.schema.json`, its example
  `contracts/examples/blind-manifest.v1.json`, a reader (`expectrail.blind_set.read`) and a writer
  (`expectrail.blind_set.write`), with the fields #742 lists. A defect entry carries `id`, `project`,
  `description`, `howItShouldBehave`, `family`, `whereItShows`, `difficulty`, `exercised`, `defectPatch`,
  `reproduction` and `candidates`. An entry that is not a fix carries `notAFixKind` and `expectedVerdict`.
  The manifest carries `declaredCounts`, `exclusions`, `sealedAt` and `sha256`. `checkMeasured` is optional
  and nothing requires it.
- `python3 -m expectrail.blind_set validate MANIFEST --project NAME=FOLDER ...`: offline, no model, never
  runs Expectrail. It reports every unmet minimum of #282 section 3 with how many more it needs, missing
  ground truth, declared counts that disagree, and patches that are missing or do not apply
  (`git apply --check` on a copy of the project; a candidate on top of its defect). It prints one PASS line
  when nothing is unmet. It prints ids and counts, never a description: a schema message that would quote
  set text is rewritten.
- The writer fills `sha256` only when the caller has set `sealedAt`, and never sets `sealedAt` itself.
- `docs/contracts.md`: a row for the new record.

## What was run
- `python3 -m unittest tests.test_blind_set`: 33 tests, OK. They use synthetic sets only: one at the
  minimum counts that passes, and copies that each break one rule.
- Four mutations of `expectrail/blind_set.py` (the screen-only quarter rounded down, the half-the-set
  rule loosened, candidates checked on the clean project instead of on the defect, `confirmedBy` not
  checked): each made the tests fail.
- Full suite: see the pull request for the run and its result.
- Nothing was dispatched and nothing was spent. No blind set was read.

## Not done
- `blind-registration/v2` (the next slice of #742) and the check that
  `bench/jit/blind-3/preregistration.json` reads as v0 or is declared out of format.
- The quotas are copied from #282 section 3 into `QUOTAS`. Once the registration exists, the validator
  should read them from it.
- No engine build of a patched project; only `git apply --check`.
- No template was attached to #742, so the field names follow the issue's text. The family slugs are the
  ones `repro-bench/v1` already uses.

## Files
- `contracts/blind-manifest.v1.schema.json`
- `contracts/examples/blind-manifest.v1.json`
- `expectrail/blind_set.py`
- `tests/test_blind_set.py`
- `docs/contracts.md`
- `docs/new-work/2026-11-21-sealed-set-manifest-validator.md`
