# Document the conditions for trusting a verification verdict (#723)

## What changed

Added a register for the risks in the November 19 verification research review, checked against
main at f50b839. It links primary sources, current code and measurements, and evidence needed to
close each risk. It maps to the seven release evaluation questions in #282.

## What was run

- Fetched the required historical commit.
- Re-ran the offline public counting audit over bench/jit/recordings/public-43465090517/repro.
  The result matched the committed report byte for byte, with 137 advisory and zero counting.
- Re-ran tools.recorded_renderer against its public fixtures. The JSON matched the committed
  measurement byte for byte, including the overlap between renderer drift and a subtle recolor.
- Resolved all 55 repository links and section references in the register.
- `python3 -m unittest discover -s tests -t .` completed successfully. Ran 5,682 tests, 82 skipped.
- Public export scan reported zero errors and zero warnings across 1,286 files.

## Not done

Fresh engine or live vision runs, a prospective outside cohort, and a trusted issuance
deployment remain open sources of evidence.

## Files

- [Verification risks](../verification-risks.md)
- This work-log entry.
