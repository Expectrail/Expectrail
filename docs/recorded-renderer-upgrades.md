# Recorded vision after a renderer upgrade (#515)

Recorded answers require the exact image bytes and question. A runner image upgrade can change
pixels even with the same game and engine. Expectrail does not tolerate pixel differences:
[the measured renderer drift overlaps a small player recolour](recorded-renderer.md).
A missing answer needs review; an engine failure can still reject. Matching renderer metadata is
not proof that all questions are recorded.

Before running a configured project, use `expectrail doctor --project /path/to/project --no-fetch`.
Without `--project`, doctor uses an `expectrail.project.json` in the current folder, if present.
The local app shows the same machine/recording comparison under **Check folders**, and checks
Before's recording before starting **Verify**. A warning asks you to read it before continuing;
it never switches observers or relaxes the verdict. Fix a mismatch by re-recording on this
renderer, or explicitly selecting live vision in the config and setting `MODEL_API_KEY` and
`EXPECTRAIL_SAM_USD_CAP` in the verifier's environment. A key alone does not override a recording.
No secret is entered into the app or written into a project file. Live vision still has to provide
all evidence required by the checks; selecting it is not a promise of accept.

## Check after a runner image upgrade

The capture job can run the following after its existing smoke capture. It uses the same engine,
virtual display and software renderer as the harness, draws only an empty probe project, and
makes no model request:

```sh
EXPECTRAIL_ENGINE_TESTS=required python -m unittest tests.test_recorded_renderer_drift.CaptureRendererTest -v
```

It names each incompatible recording, both engine/renderer/device versions, and recordings whose
provenance is unknown. Outside that required CI setting, a missing engine, display or renderer is
a named skip, not a match. It scans `docs/run-it/vision/*.json` and vision-recording documents under
`tests/outside/recordings/`. The offline comparison and app/doctor tests also run in the full suite.

**Initial rollout:** the four Run it files currently have no rendering metadata. Their old workflow
artifacts contain only answers, not the captures; the inspected record-job logs do not identify
the rendering device. The check deliberately fails for that unknown provenance. Do not fill it
from an assumption about an Ubuntu image. Recover the original `replay.json` or re-record before
enabling this check. The kinematic recording identifies llvmpipe LLVM 20.1.2; this development
machine reports 19.1.7 and is correctly reported as different.

## Re-record (only Sean dispatches)

1. Read the failing capture check and keep its old/new environments with the proposed update.
2. Ensure the recording-provenance writer is on main. In GitHub **Actions → Run it record → Run
   workflow**, select **main**, choose one target, and enter the maximum Sean authorizes in
   `sam_usd_cap`. The workflow accepts more than zero and at most `2.00`; that is a cap, not a price
   estimate. Repeat for `clean`, `fall-through-bug`, `fall-through-repair` and `gate-combat` as needed.
3. Sean approves the existing protected environment. Keep the two jobs separate: the recording job
   holds the key but cannot write the repository; the proposal job holds no key and runs no game.
   Open the proposal link printed by the workflow, review the actual spend and the new
   `renderingEnvironments`, and compare capture/recording provenance before merging. `gate-combat`
   is a gate recording, not a website sample.
4. For an outside recording, Sean uses **Actions → Outside vision → Run workflow**, **main**, the
   project, and his chosen cap. Keep `outside-captures` and `outside-vision-findings` artifacts.
   Review the recording and corresponding calibration from that same run before proposing their
   replacement under `tests/outside/recordings/PROJECT/`. Never change a check's approval as part
   of refreshing recorded answers.
5. Re-run the capture drift check and the applicable sample/outside replay checks without a live
   key. Verify the expected verdicts as well as metadata: this guard checks the environment, not
   every pixel or question. Publish the run links, request counts and actual spend with the update.

## What the existing recordings cost

These are counts of the checked-in `answers` arrays, and historical run figures, **not estimates
for another recording**. One saved answer is a unique image/question entry. Repeated questions,
calibration and unanswered calls mean saved-entry counts need not equal requests or images billed.
The JSON alone cannot recover a run's total requests or spend. Values below are from the linked
successful recording jobs or the published outside-run report; no new recording was made.

| Recording (saved unique answers) | Actual requests in that run | Images answered | Recorded spend at list price | Source |
| --- | ---: | ---: | ---: | --- |
| [clean: 120](run-it/vision/clean.json) | 120 | 120 | $0.3000 | [record job](https://github.com/Expectrail/Expectrail/actions/runs/43508479160/job/132172223355) |
| [fall-through-bug: 135](run-it/vision/fall-through-bug.json) | 135 | 135 | $0.3375 | [record job](https://github.com/Expectrail/Expectrail/actions/runs/43508788240/job/132173294443) |
| [fall-through-repair: 135](run-it/vision/fall-through-repair.json) | 135 | 135 | $0.3375 | [record job](https://github.com/Expectrail/Expectrail/actions/runs/43509232715/job/132174831533) |
| [gate-combat: 100](run-it/vision/gate-combat.json) | 204 | 200 | $0.5100 | [record job](https://github.com/Expectrail/Expectrail/actions/runs/43676005540/job/132696187564) |
| [kinematic-character: 429](../tests/outside/recordings/kinematic-character/vision-recording.json) | 802 | 800 | $2.0000 (cap reached) | [judge job](https://github.com/Expectrail/Expectrail/actions/runs/43652198623/job/132623245351), [published report](outside-projects.md#first-outside-game-verified-with-vision-november-14-2026) |

The outside row covers the recorded run's variants together, not a per-variant cost. No predicted
re-record cost follows from these figures. Sean chooses the cap; a capped or incomplete recording
must not be presented as complete evidence.
