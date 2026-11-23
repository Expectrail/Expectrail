# Check the manifest against the public registration (#742)

## What changed

The existing offline manifest command accepts an optional `--registration`. It reads the v2 protocol
through the existing reader and uses its minima and quotas. It requires matching project names
and checks the sealed manifest digest when the registration supplies one. An unsigned draft can
support pre-seal validation. The existing command still uses the protocol's default quotas when
called with a manifest alone.

## What was run

Before implementation, two focused tests failed on the absent API argument and unrecognized CLI
option. The regression tests use synthetic records for quota source, invalid registration,
project mismatch and matching or stale digest.

- All 47 focused registration and manifest tests passed.
- The checkout command reported PASS on three pinned synthetic Git checkouts after the patch
  checks. It reported 30 wrong fixes, 20 correct fixes and 10 other changes.
- The full `python3 -m unittest discover -s tests -t . -v` suite on base `4b6ba69` completed
  6,010 tests with 81 skipped and zero failures.

## Not done

Engine build checks for patched projects and the release runner remain separate. Real registration
thresholds, sign-off, the seal and protected dispatch belong to Sean.

## Files

- `expectrail/blind_set.py`
- `tests/test_blind_set.py`
- `docs/contracts.md`
