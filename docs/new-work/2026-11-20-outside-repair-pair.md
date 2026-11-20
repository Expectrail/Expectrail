# Four proposed repairs in the same outside game

## What changed

Issue #370 asks whether a developer can compare a plausible wrong fix with a working one. The outside trial submits four candidates through the configured local app backend. They all start from the same broken Before copy of the public kinematic-character game at upstream commit `b761b4cd5718a7118f2c95eb55f181d0a5f004f1`. Before has its collision mask disabled. All four use the same approved check, walk recording, saved vision answers and calibration.

| Candidate | Change from Before | Rehearsal control for the After walk |
| --- | --- | --- |
| Mask 2 | Select another collision layer | Reject. The walk check must still fail in the engine. |
| Hidden sprite | Restore collision and set the sprite's `visible` property to false | Reject. The engine cannot measure the hidden player. Recorded vision finds it missing. |
| Stuck fade | Restore collision and leave the sprite visible in the scene tree with its alpha at zero | Reject, with the engine check passing and recorded vision failing |
| Restored | Restore the original scene | Accept, with both observers passing |

The app uses its normal intent and requests isolated execution. After recording each actual verdict, the rehearsal checks the controls and verifies isolation. A missed control fails the step with a reason. The separate registry trial retains its own outcome. The job log and summary show the individual observer results and paired visual anchor coverage. The artifact contains each available offline evidence page, the five input tree digests and the engine readings at the first finding frame, measured difference or limit crossing. A physics tick is included when the capture records it. The workflow also uploads results from failed steps. Verification checks that all five input trees keep their original digests.

## What was run

The initial hosted app comparison ran two isolated replays per candidate. Mask 2 was rejected after the engine failed the check. Vision was not asked. The restored scene was accepted with both observers passing. [Hosted two-candidate comparison](https://github.com/Expectrail/Expectrail/actions/runs/44726059532)

A gate evaluation of archived captures rejected the hidden sprite. The engine passed and recorded vision failed at frame 0. With a developer project configured through the app, the engine observes the bound sprite's visibility in the scene tree. In the hosted hidden-sprite submission the engine found the player in zero of 120 window frames and judged zero. The engine returned needs-review, vision gave no answer and the app returned needs-review after two isolated replays. This was the result before the installed reader could validate negative visual observations. [Archived source captures](https://github.com/Expectrail/Expectrail/actions/runs/43652198623) · [Hosted configured comparison](https://github.com/Expectrail/Expectrail/actions/runs/44729024185)

The saved calibration reported 19 found in 19 asked frames. All eight combinations of the previous step outcome and cancellation matched the intended schedule in a local expression check. As a formatter check, the archived pinned-to-broken capture produced before engine/vision pass/pass, after fail/not-asked, finding frame 44 and 71.749 px past the boundary. [Archived source captures](https://github.com/Expectrail/Expectrail/actions/runs/43652198623)

Locally, the four-candidate app submission returned needs-review at preflight for each candidate. Bubblewrap could not set up its UID map on this host. There were zero isolated replays and zero check results. The JSON retained all four outcomes, and the step reported the missing evidence and exited 3. All four prior input tree digests matched the hosted three-candidate run, and an independent application of the fade patch reproduced the fifth tree digest. The 65 focused tests passed. The full suite ran 5,593 tests with 78 skipped, zero failures and zero errors. The export scan checked 1,256 files with zero warnings or errors.

After the reader repair in #701, the configured app rejected both visual regressions. Recorded vision found the player missing from 83 of 120 frames in each, starting at frame 0 (physics tick 1). For the stuck fade, the runtime measurement was valid and identical on both sides at that tick. For the hidden sprite, the runtime player was missing and the engine returned needs-review. The restored game passed both observers. All eight replays ran under required isolation, and all ten registry cases matched. The rehearsal step failed on its previous hidden-sprite expectation. It now requires the visual rejection and keeps the separate engine-pass requirement for the stuck fade. [Hosted job and artifact](https://github.com/Expectrail/Expectrail/actions/runs/44755124153/job/136352713821)

In offline Chromium the exported mask-2 viewer jumped to frame 44, both visual failures jumped to frame 0 and the restored viewer jumped to frame 20, its first measured difference. Each of those jumps showed both 530 × 495 captures. All four pages opened with zero external requests or JavaScript errors.

## What remains

An unaided developer's time to a verdict, their ability to find the decisive frame in the UI and their next action require a session on their own game.

## Files

- `docs/outside-projects.md` links the hosted evidence and explains which frame to inspect.
- `.github/workflows/outside-trial.yml` runs the rehearsal and uploads the public results.
- `tests/outside/repair_pair.py` prepares the candidates, submits the comparisons and checks the results.
- `tests/outside/repair-pair/wrong-mask-repair.patch` changes the disabled mask to layer 2.
- `tests/outside/repair-pair/stuck-fade.patch` leaves the restored player's sprite at zero alpha.
- `tests/test_outside_repair_candidates.py` checks the four candidate controls and missing evidence.
