# Playtester reach and false reports at scale (#531, round two)

**Clean-game reports: development original 0/200 seeds; fresh paired original 0/200; fresh improved 0/200.** These are report counts; see reporting-seed counts below. The new observer did not increase clean false reports in the paired sample.

The complete measurement used **10,400 successful primary replays**: 200 development seeds (0–199) and 200 fresh evaluation seeds (10000–10199), each on the clean game and 25 public patches. Every route starts at the game’s start and runs 1,200 physics ticks. Base: `a98dcb08c2d7fe068283e97148b07a37d423d91e`. Pinned engine: **Godot 4.7.2.stable.official.ed1daf0bf**, downloaded by `harness/get_godot.sh` with its SHA-512 check. No model, fixer or paid API call was made by the measurement.

The public universe is the strict `bench/jit/public/defects.json` plus every `bugs/reported/*.patch`, deduplicated by listed patch. It contains **24 defects and one upstream fix**, `platform-z-order-pr927`. The four shared reported defects run once, not twice. The draw-order patch is shown because it was requested, but is excluded from the defect denominator. The 24 defects comprise four reproductions of reported bugs and 20 written public-bench fixtures; this is public development, not blind discovery. No private, blind or `fresh-*` content was used. The upstream fix is excluded from found/missed defect rates; its row records reports and observability only.

## False reports first

Every report on the clean game is false by the requested definition, with no exemptions. All 200 clean development runs finished before any development defect run. The fresh clean runs likewise finished before fresh defect runs.

| Observation | Development original | Fresh original | Fresh improved | Clean examples |
| --- | ---: | ---: | ---: | --- |
| below-level | 0 | 0 | 0 | none occurred |
| stopped-moving | 0 | 0 | 0 | none occurred |
| turning | 0 | 0 | 0 | none occurred |
| offscreen | not enabled | not enabled | 0 | none occurred |

Seeds with at least one false report: 0/200 development, 0/200 fresh original, 0/200 fresh improved. There are no two-example pairs to show where the count is zero; no synthetic examples are substituted. Zero observed false reports on this one game and these bounded routes is not proof of a zero general false-report rate.

## Initial reach: all public patches

A **candidate** means an observation not also reported on the clean game on that same seed. Reports already present on the clean seed are not new defect candidates. A candidate is not automatically the listed bug: immobility can describe an obstruction. The visible-symptom column is a conservative interpretation of the report wording against the public report, not a generated check or cause diagnosis. Turning matches body-flip; persistent offscreen reports match camera complaints only when the recorded edge matches the complaint (right or top). Other consequences remain candidates.

Initial producer reports: **214**, from **4 patch builds**. Directly described listed symptoms: **1/24 defects**. The 21 development immobility candidates do not demonstrate infinite jumping, sliding after release, or inability to jump while running.

| Defect / requested fix | Candidate report seeds, first seed, observation | Listed visible symptom found | Miss reason for listed symptom |
| --- | --- | --- | --- |
| `air-jump` | 2/200; first 2; stopped-moving 2 | no | `wrong-predicate` |
| `gun-cooldown` | 0/200; first —; none | no | `wrong-predicate` |
| `body-flip` | 193/200; first 0; turning 193 | yes | `-` |
| `enemy-ledge` | 0/200; first —; none | no | `wrong-predicate` |
| `bullet-through-enemy` | 0/200; first —; none | no | `wrong-predicate` |
| `platforms-not-solid` | 0/200; first —; none | no | `wrong-predicate` |
| `floaty-fall` | 0/200; first —; none | no | `wrong-predicate` |
| `jump-always-full` | 0/200; first —; none | no | `wrong-predicate` |
| `slow-left` | 0/200; first —; none | no | `wrong-predicate` |
| `slides-after-stop` | 1/200; first 177; stopped-moving 1 | no | `wrong-predicate` |
| `no-shooting-in-air` | 0/200; first —; none | no | `wrong-predicate` |
| `jump-needs-rest` | 18/200; first 5; stopped-moving 18 | no | `wrong-predicate` |
| `double-jump-once` | 0/200; first —; none | no | `wrong-predicate` |
| `coin-stays` | 0/200; first —; none | no | `wrong-predicate` |
| `coin-counts-twice` | 0/200; first —; none | no | `route-never-reaches` |
| `coin-counter-stuck` | 0/200; first —; none | no | `route-never-reaches` |
| `gun-cooldown-long` | 0/200; first —; none | no | `wrong-predicate` |
| `enemy-missing` | 0/200; first —; none | no | `wrong-predicate` |
| `enemy-fast-left` | 0/200; first —; none | no | `wrong-predicate` |
| `enemy-slides-when-shot` | 0/200; first —; none | no | `wrong-predicate` |
| `enemy-walks-backwards` | 0/200; first —; none | no | `probe-language` |
| `camera-stops-right` | 0/200; first —; none | no | `wrong-predicate` |
| `camera-cut-top` | 0/200; first —; none | no | `wrong-predicate` |
| `bullet-behind-scenery` | 0/200; first —; none | no | `probe-language` |
| `platform-z-order-pr927` | 0/200; first —; none | no | `probe-language` |

## Why the misses were missed

The reason names are exactly `expectrail.repro.score.MISS_REASONS`, explained by `expectrail/repro/breakdown.py`. They describe this engine-only measurement, not a live generated-check score. A changed existing signal gives `wrong-predicate`; differing fields with no changed existing signal give `no-signal`. Any signal change counts, including incidental small changes, so it does not by itself prove the named behavior was reached.

| Reason used | Evidence / limit |
| --- | --- |
| `wrong-predicate` | Current seeded trace comparisons show an existing repro signal changes, but no producer report establishes the listed symptom. The JSON summaries retain changed fields/signals and first differing seed. |
| `no-signal` | A trace field changes without an existing repro signal changing. Used only when current records show that condition. |
| `route-never-reaches` | `coin-counts-twice` and `coin-counter-stuck`: these routes never open the pause menu. `repro.menu` and public menu evidence document that the counter is drawn there and is not logged in the trace. |
| `probe-language` | Public evidence describes enemy-facing, bullet-layering or platform draw order that these traces do not record. This uses identified existing public screen/draw evidence, not a new rendered replay of these seeded routes. |
| `undetermined` | Matching traces/signals without evidence separating missing reach from an unrecorded effect. No guess that such a defect was never reached. |

`flaky` and `budget` remain in the fixed vocabulary but are not inferred from a recovered engine crash or from the absence of model spend. Most initial misses already change recorded signals. This breakdown therefore motivated an observation change rather than a new route policy.

## One frozen improvement, then fresh paired evaluation

The one change is an optional observation: a visible bound player’s entire recorded body stays outside the game view for one physics second. It uses the existing body box and affine view transform; all four corners must be outside on one side, and partial/touching-edge visibility does not count. Missing, hidden, invalid or degenerate samples break the window. The duration comes from the physics rate, not a known defect’s timing. No defect identity, report text, profile mechanics, jump-height or weapon-cooldown parameter enters it.

The routes and the original three observation functions are unchanged. Their source segments match the prerequisite, and all 214 original positive reports regenerated identically after the API extension. Original mode remains version 1.0.0; `--viewport 800 480` enables the combined mode, version 1.1.0. Both preserve the exact issue-table report shape, complete start route and previous-tick world anchor.

The pinned-engine probe measured the headless logical view as **800×480 at (0,0), identity final transform**. The 64×64 dummy window and normal 1600×960 capture are different coordinate systems. These dimensions were verified before freezing, not fitted to evaluation results. `frozen-improvement.json` contains source hashes, the one-second rule and proof that the evaluation directory did not exist at freeze. No runtime source was changed afterward.

Fresh evaluation uses both policies on the **same** 200 routes and engine traces per build. Thus policy differences are paired, while the development set remains separate. All clean reports are false, including any new offscreen report; none can be explained away. Geometry is an engine prediction, not rendered-pixel proof, and intentional transitions or artwork/collision differences can confound it.

Fresh listed visible symptoms found: **1/24 original → 3/24 improved**. Candidate-bearing patches: **3 → 6**, including the separately labelled requested fix. Candidate counts are not a verified repair or bug-discovery rate.

| Defect / requested fix | Fresh original: seeds / first / observations | Fresh improved: seeds / first / observations | Listed visible symptom original → improved | Improved miss reason for listed symptom |
| --- | --- | --- | --- | --- |
| `air-jump` | 0/200; first —; none | 23/200; first 10001; offscreen 23 | 0/200 → 0/200 | `wrong-predicate` |
| `gun-cooldown` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `body-flip` | 190/200; first 10000; turning 190 | 190/200; first 10000; turning 190 | 190/200 → 190/200 | `-` |
| `enemy-ledge` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `bullet-through-enemy` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `platforms-not-solid` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `floaty-fall` | 1/200; first 10156; stopped-moving 1 | 1/200; first 10156; stopped-moving 1 | 0/200 → 0/200 | `wrong-predicate` |
| `jump-always-full` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `slow-left` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `slides-after-stop` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `no-shooting-in-air` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `jump-needs-rest` | 18/200; first 10001; stopped-moving 18 | 18/200; first 10001; stopped-moving 18 | 0/200 → 0/200 | `wrong-predicate` |
| `double-jump-once` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `coin-stays` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `coin-counts-twice` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `route-never-reaches` |
| `coin-counter-stuck` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `route-never-reaches` |
| `gun-cooldown-long` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `enemy-missing` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `enemy-fast-left` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `enemy-slides-when-shot` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `wrong-predicate` |
| `enemy-walks-backwards` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `probe-language` |
| `camera-stops-right` | 0/200; first —; none | 86/200; first 10007; offscreen 86 | 0/200 → 86/200 | `-` |
| `camera-cut-top` | 0/200; first —; none | 4/200; first 10068; offscreen 4 | 0/200 → 4/200 | `-` |
| `bullet-behind-scenery` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `probe-language` |
| `platform-z-order-pr927` | 0/200; first —; none | 0/200; first —; none | 0/200 → 0/200 | `probe-language` |

Offscreen reports on air-jump or other physics builds are visible consequences, not an infinite-jump or physics-specific check. Immobility candidates remain unconfirmed against their named symptom. The geometry-side evidence for every new offscreen report is in `offscreen-evidence.json`; every report document is in the handover.

## What was run and retained

- Full suite before, all `EXPECTRAIL_*` variables removed: **Ran 4086 tests in 459.386s; OK (skipped=48); exit 0**. No failing unittest test names.
- Full suite after, all `EXPECTRAIL_*` variables removed: **Ran 4115 tests in 745.594s; OK (skipped=48); exit 0**. No failing unittest test names.
- Focused producer/scale/offscreen tests: **29 passed**, including fresh-process imports with numpy and PIL blocked.
- Raw readback audits verified complete traces, trace/replay hashes, exact build blobs, route regeneration, field/signal recomputation, report regeneration, issue-table shape and actual previous-tick anchors. Both evaluation policies were audited from the same raw traces.
- Two selected fresh routes (body-flip seed 10000 and air-jump seed 10001) were each replayed three more times: all six full trace hashes and both policies’ report ID sets matched. This is a selected-route stability result, not a three-run claim for every seed.
- The first standalone stability-script invocation could not import the repo; rerunning with the repo on PYTHONPATH succeeded. The launch-error and successful logs are preserved; the failed import started no engine replay.
- Commands, resumption rules and viewport assumptions: [tools/playtester/SCALE.md](../tools/playtester/SCALE.md).

Engine failures were retried only as failed attempts, up to three total attempts per invocation; they are not counted as successful routes or as reports. All requested seeds have a final valid measurement. Recovered failures:

| Phase | Build | Seed | Failed attempts before success |
| --- | --- | ---: | ---: |
| development | bullet-behind-scenery | 27 | 1 |
| evaluation | bullet-through-enemy | 10030 | 1 |

Total recovered failed engine attempts: **2**. Their engine crash logs are retained. An earlier progress message said no replay failures before the complete audit surfaced the recovered development failure; that statement was corrected.

The zip contains combined and incremental patches, base/title/body, the work log inside the patch, complete before/after suite logs and exit codes, all report documents, all 10,400 per-seed measurement/replay/engine records, plans/freeze/audits and all raw trace hashes. To keep the handover manageable, it includes selected raw trace witnesses: first routes, first changed record/signal witnesses with clean counterparts, first two report examples per observation/build/policy where present, and clean endpoints. **Other raw traces remain in the local measurement directories and are omitted from the zip**, as are game copies/import caches. `TRACE_SELECTION.json` identifies the exact selection and every raw hash. Re-running the documented commands regenerates the full raw data; the full auditor requires that full data.

## Not done

No rendered frames or visual model observations, shared-verifier/ingest integration, generated checks, fixer, approvals, end-to-end repair rate, private/held-out run, push, GitHub comment or PR. The schema and ingest work remain with the other #531 builder. This measures bounded seeded inputs and trace observations; it does not establish general platformer correctness or usability beyond the reported sample.
