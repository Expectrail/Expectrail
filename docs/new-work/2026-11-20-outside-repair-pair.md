# Three proposed repairs in the same outside game

## What changed

Issue #370 asks whether a developer can compare a plausible wrong fix with a working one. The outside trial now exercises the local app backend with four prepared copies of the public kinematic-character game at upstream commit `b761b4cd5718a7118f2c95eb55f181d0a5f004f1`. Every submission starts with the same disabled collision mask. The three candidates select collision layer 2, restore collision while hiding the player sprite, or restore the original scene. The hidden-sprite candidate applies the existing public invisible-player patch to the restored game. All three use the same approved check, walk recording and calibration. The rehearsal submits the configured project with the app's normal intent, requests isolation and polls the app for each result.

The repair comparison runs after the legacy project trial completes, even when that trial fails. Both retain their own outcome. The public step log and job summary report the saved calibration and what the runtime check and visual check each observed, including a visual check that was never asked. Both list the paired visual anchor coverage separately. At the first finding frame, first measured difference or first measured limit crossing, the JSON includes the engine readings on both sides and any physics tick recorded by the capture timeline. A missing tick stays empty. The artifact includes the four input tree digests and the offline evidence page for each available result. After recording the app verdicts, the rehearsal checks that mask 2 was rejected, the hidden sprite was rejected with the After engine check passing and vision failing on the walk, and the restored scene was accepted with both After observers passing on the same check. All three need completed, isolated replays. A missed control prints the reason and fails the step. The workflow also uploads evidence from failed steps. The rehearsal checks that verification leaves all four inputs untouched.

## What was run

The focused repair-control, app-project, renderer-closeout, outside-trial, outside-root and work-log suites passed 64 tests. The full suite ran 5,592 tests with 78 skipped, zero failures and zero errors. The export scan checked 1,256 files with zero warnings or errors. A local run with the pinned game and isolation required reached the app on all three submissions. All three returned `needs-review` during preparation with `TOOL_MISSING`. Bubblewrap could not set up its UID map on this host. Zero replays and zero check results were recorded. The rehearsal exited 3 through the log-and-summary pipeline. The saved calibration reported 19 found in 19 asked frames. The original three folder digests matched the hosted run, and applying the registered invisible-player patch independently to the restored folder reproduced the fourth digest.

All eight combinations of the previous step outcome and cancellation matched the intended schedule in a local expression check. As a formatter check, the archived pinned-to-broken capture produced before engine/vision pass/pass, after fail/not-asked, finding frame 44 and 71.749 px past the boundary. That capture came from [the earlier public run](https://github.com/Expectrail/Expectrail/actions/runs/43652198623).

The first hosted app comparison ran two isolated replays per candidate. Mask 2 was rejected after the engine failed the check and the visual check was not asked. The restored scene was accepted with both checks passing. [Hosted two-candidate comparison](https://github.com/Expectrail/Expectrail/actions/runs/44726059532)

A separate evaluation of previously captured frames compared the same disabled mask with the restored collision and hidden sprite. The engine check passed. Recorded vision failed at frame 0, leading to rejection. The earlier captures establish the inputs for the third app submission. [Public source captures](https://github.com/Expectrail/Expectrail/actions/runs/43652198623)

## What remains

A new hosted run must measure the hidden-sprite candidate through the configured app backend. This rehearsal measures the app backend on prepared public copies. An unaided developer's time to a verdict, their ability to locate the first decisive frame in the UI and their next action require a session on their own game.

## Files

- `.github/workflows/outside-trial.yml` runs the rehearsal and uploads its public results.
- `tests/outside/repair_pair.py` prepares all three submissions and reads the app results.
- `tests/outside/repair-pair/wrong-mask-repair.patch` changes the disabled mask to layer 2.
- `tests/test_outside_repair_candidates.py` checks for incorrect repair outcomes, missing observers and incomplete isolation evidence.
