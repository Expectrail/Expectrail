# Two approval-reader holes closed (#420)

## What changed
The #420 builder reproduced two holes in `expectrail/approval.py`'s reader on main 791f50b and lost its
workspace before handing them back; this is that fix, written again. `state()` now calls both
`mismatch` (never approved):
- an approval whose `by` is missing, blank or not text, even when its digest matches;
- an approval carrying any other digest field (`specSha1`, `specSha512`, `spec_sha256`…). Renaming
  `specSha256` used to make it read as a legacy approval, which still counts.

## What was run
- `tests.test_approval_binding`: 26 tests OK, three of them new.
- Every approved spec in the repository read with the new reader: 16 legacy and 1 bound, all with
  a reviewer named and no other digest field, so none changes state.
- Full suite: see the pull request.

## Not done
The approve command trusts the name it is given; it does not authenticate the person. The 16 legacy
approvals still count and are named "approved before content binding"; re-approving them binds them
to their content (Sean's step).

## Files
- expectrail/approval.py
- tests/test_approval_binding.py
- docs/new-work/2026-11-18-approval-reader-holes.md
