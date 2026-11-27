# One approval sitting before blind set 4 is sealed

## What changed

`docs/approval-sitting.md` gathers every check draft that is ready for Sean's approval today, with
the control evidence behind each, so the sitting happens once instead of per project. It names five
ready checks, recommends holding one, rules one not ready, and explains why two defect families
cannot be approved at all yet.

The five cover four of the six defect families that have nothing able to reject a defect, taking
family coverage from four of ten to eight of ten.

`docs/outside-trials/breakout-pointer/checks-for-approval.md` now links the combined sitting, and
both documents use `--by "Sean Keluo-Udeke"` in their approval commands. The `by` field is written
verbatim with no allowlist (`expectrail/approval.py`), and all four approvals in the repository read
`Sean Keluo-Udeke`, so `--by sean` would have recorded a second approver identity in the one field
that records a human decision (#749). Older documents still show the `--by sean` form; they describe
specs already approved and are left as the records they are.

## What was run

- Every relative link in `docs/approval-sitting.md` resolved: 16 of 16.
- `python3 -m expectrail.spec_writer approve --help` confirmed the signature is `approve [-h] --by BY path`.
- Read the stored `approval` of `specs/player-always-visible.json`, `specs/coins-visible.json` and
  `tests/outside/specs/dodge-play-area.json`: each reads `Sean Keluo-Udeke`.
- Confirmed every assertion and coverage type used by the eight candidate drafts is implemented:
  `inside-region`, `never-crosses`, `visible`, `reaches`, `exact-ui-integer`, `position-at-tick`,
  `position-region`, `role-displacement`.
- Confirmed `tests/outside/projects.json` points the registered `breakout` project's `config`,
  `routes` and `draftSpecs` at `tests/outside/breakout-pointer/`, so the coarser same-id files under
  `tests/outside/breakout/checks/` are loaded by nothing today.
- `TZ=UTC python3 -m unittest tests.test_approval_binding tests.test_ci_gate tests.test_contracts
  tests.test_outside_root tests.test_outside_trial` -> 218 tests, OK.
- The full suite was not run here; the merge guard runs it on the merged result.

## Not done

No spec was approved and no `approval` field was written: that is Sean's act alone. The cleanup this
page asks for — removing the superseded same-id drafts under `tests/outside/breakout/checks/` — is
not done here either, so that the sitting and the deletion are judged separately.

## Files

`docs/approval-sitting.md`, `docs/outside-trials/breakout-pointer/checks-for-approval.md`.
