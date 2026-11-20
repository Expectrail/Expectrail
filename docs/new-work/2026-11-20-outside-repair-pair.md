# Two proposed repairs in the same outside game

## What changed

Issue #370 asks whether a developer can compare a plausible wrong fix with a working one. The outside trial now exercises the local app backend with three prepared copies of the public kinematic-character game at upstream commit `b761b4cd5718a7118f2c95eb55f181d0a5f004f1`. Both submissions start with a disabled collision mask. One candidate selects collision layer 2. The other restores the original scene. Both use the same approved check, walk recording and calibration. The rehearsal submits the configured project with the app's normal intent, requests isolation and polls the app for each result.

The repair comparison runs after the legacy project trial completes, even when that trial fails. Both retain their own outcome. The public step log and job summary report the saved calibration and what the runtime check and visual check each observed, including a visual check that was never asked. Both list the paired visual anchor coverage separately. At the first finding frame, first measured difference or first measured limit crossing, the JSON includes the engine readings on both sides and any physics tick recorded by the capture timeline. A missing tick stays empty. The artifact includes the three input tree digests and the offline evidence page for each available result. The rehearsal checks that verification leaves all three inputs untouched.

## What was run

The focused outside-trial, outside-root and work-log suites passed 39 tests. The full suite ran 5,588 tests with 78 skipped, zero failures and zero errors. The export scan checked 1,256 files with zero warnings or errors. A local run with the pinned game and isolation required reached the app on both submissions. Both returned `needs-review` during preparation with `TOOL_MISSING`. Bubblewrap could not set up its UID map on this host. Zero replays and zero check results were recorded. The rehearsal exited 3 through the log-and-summary pipeline. The saved calibration reported 19 found in 19 asked frames.

All eight combinations of the previous step outcome and cancellation matched the intended schedule in a local expression check. As a formatter check, the archived pinned-to-broken capture produced before engine/vision pass/pass, after fail/not-asked, finding frame 44 and 71.749 px past the boundary. That capture came from [the earlier public run](https://github.com/Expectrail/Expectrail/actions/runs/43652198623).

## What remains

The hosted job must produce its own comparison. This rehearsal measures the app backend on prepared public copies. An unaided developer's time to a verdict, their ability to locate the first decisive frame in the UI and their next action require a session on their own game.

## Files

- `.github/workflows/outside-trial.yml` runs the rehearsal and uploads its public results.
- `tests/outside/repair_pair.py` prepares both submissions and reads the app results.
- `tests/outside/repair-pair/wrong-mask-repair.patch` changes the disabled mask to layer 2.
