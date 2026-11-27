# Update the public reproduction dispatch handoff (#285)

## What changed

The reproduction audit records that both live model steps receive the per-defect sender cap and use the protected `spend` environment. It dates the original missing-cap result and links the fix. This gives Sean the current starting point for the Q7 reproduction measurement in #282. [Sender-cap change](https://github.com/Expectrail/Expectrail/pull/618) · [Spend approval](../spend-environment.md)

## What was run

- Parsed the workflow on main `a28d6f56` and checked the per-defect cap binding on the proposal and revision steps. Compared the five published dispatch commands byte for byte with main.
- Queried public GitHub Actions dispatch metadata. The latest dispatch from main remained the November 13 baseline. [Baseline run](https://github.com/Expectrail/Expectrail/actions/runs/43465090517)
- All 25 focused audit, aggregate-report and work-log tests passed.
- Fetched the required historic commit. Full discovery with packaging tests required passed with 6,048 tests run and 80 skips in 830.914 seconds.

## Not done

The fresh revised-rule public reproduction measurement awaits Sean’s protected dispatch and approval.

## Files

- `docs/repro-audit.md`
- `docs/new-work/2026-11-27-reproduction-dispatch-handoff.md`
