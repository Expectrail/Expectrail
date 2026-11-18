# Observer policy in the offline CI jobs (#327, PR #602)

## What changed

The proposed CI diff selects the legacy trace diagnostic in the five repair-loop jobs. The verifier
prints the diagnostic label and includes it in the saved reasons that feed the morning report.
The release coverage control now runs the existing recorded-vision gate command on both sides of
its missing-route test. It checks the observer name and rule as well as the original decisions.
The public clearance job already selects the base checkout's recording bank.

## What was run

The real judge command evaluated capture artifact 14362733930 from PR #602 using the rebased code.
Smoke and combat both passed with the engine and recorded vision. Four sandboxed replays contributed.
The hosted judgment for the same head is [run 44161624171](https://github.com/Expectrail/Expectrail/actions/runs/44161624171).
All five diagnostic jobs passed their workflow assertions, including two identical 120-frame
replays and a frozen-player rejection on Godot 4.7.2. The recorded-vision held-out-route
control passed in 222.907 seconds. The full release command exited 1. Four class setups could
not create a bubblewrap UID map and three had less than 1 GiB of scratch space at preflight.
It ran 39 tests with seven setup errors. The handover has each job’s commands and logs.

Full discovery ran 4,773 tests before (one Git worktree setup error, 62 skipped).
The final after run took 489.889 seconds with one failure and 62 skips. The worker-loss
check took 0.523 seconds against a 0.5-second limit. Two earlier runs also missed the same
limit while the native release job was active. The
handover names each failure and includes the focused retries. The import check loaded 4,883
cases without NumPy or Pillow. The export scan found no errors or warnings.

## Not done

Sean applies the workflow proposal and pushes the rebased branch. A new hosted run and the live
15-candidate benchmark remain pending.

## Files

- `agents/verifier.py`
- `tests/test_default_vision.py`
- `tests/release_gate/gate_coverage.py`
- `docs/proposals/327-ci.yml.txt`
- This work log.
