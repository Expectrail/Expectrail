# Read signed hub findings offline (#713)

## What changed

A reader in `hub/receipts.py` verifies the receipt against the caller's current
trust store. It binds the signature to the independently supplied repository and
verified commit, checks the receipt's validity window, and requires the signed
digest of `report/findings.json`. A missing receipt, invalid signature or
unavailable evidence raises a distinct refusal before a verdict can be shown.
It handles the supplied bytes in memory.

The seam in `expectrail/viewer.py` reuses the findings viewer on authenticated
published data. It displays the receipt's verdict verbatim and requires the
findings record to agree. The findings reader checks record consistency, which
can refuse inconsistent evidence. The page does not execute published HTML and
does not store artifacts. This view includes findings and checks and labels the
absence of frames.

Guard: test change intended (#713)

## What was run

- The required historical fetch completed.
- Before the change, `python3 -m unittest discover -s tests -t .` on
  `b27dd903` ran 5,661 tests in 894.055 seconds and passed with 78 skips.
- The receipt, viewer and timeline focus ran 81 tests and passed. The six new
  receipt tests passed with socket connections explicitly blocked. Chromium
  opened all three verdicts from the existing viewer seam offline and made
  zero requests.
- At `0822f1a3` plus this change, the full suite ran 5,682 tests in 964.805 seconds and passed with 78 skips.

## Not done

Repository access, the runs list, artifact retrieval, frames and route registration
depend on #712's design, route registry and installation stub. This reader verifies
the published verdict, not clearance for an independently known build and policy.
The tests use public fixtures and throwaway signing keys. No developer repository
was fetched, checked out, executed or stored.

## Files

- `hub/receipts.py`
- `expectrail/viewer.py`, the seam for the existing evidence page
- `tests/test_hub_runs_receipts.py`
- This work log
