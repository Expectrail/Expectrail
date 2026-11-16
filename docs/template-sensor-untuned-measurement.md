# Frozen template sensor on untuned public frames (#262)

**The two-source under-2% bar is not demonstrated.** The frozen #522 bank gives
**8/438 (1.83%)** pooled platformer clean alarms, but the new platformer route is
**8/341 (2.35%)**. The different-art outside project gives **540/540 (100%)** with
that robot bank. Its project-specific bank cannot be built under the frozen alpha
requirements. These are findings, not a failed experiment or permission to change
what counts toward a verdict. The sensor remains opt-in.

## Clean results

“New pixels” excludes every PNG hash seen in the earlier 2,190-frame #262 corpus.
All evaluation images on the outside robot-bank arm are new to that bank. Neither
scores nor image appearance decide an exclusion; the rule was written before capture.

| Source / bank / route | Raw clean alarms | New-pixel clean alarms | Prior hashes excluded | Presence unknown | Region evidence |
| --- | ---: | ---: | ---: | ---: | --- |
| Platformer / unchanged #522 / coins | 0/120 (0.00%) | 0/97 (0.00%) | 23 | 0 | complete |
| Platformer / unchanged #522 / new route | 8/360 (2.22%) | 8/341 (2.35%) | 19 | 0 | missing on the same 8 absence-alarm frames |
| **Platformer pooled** | **8/480 (1.67%)** | **8/438 (1.83%)** | **42** | **0** | no ground crossings; 8 missing region proofs |
| kinematic-character / robot bank / walk | 180/180 (100%) | 180/180 (100%) | 0 | 0 | platformer floor map inapplicable |
| kinematic-character / robot bank / new route | 360/360 (100%) | 360/360 (100%) | 0 | 0 | platformer floor map inapplicable |
| **kinematic-character / robot bank pooled** | **540/540 (100%)** | **540/540 (100%)** | **0** | **0** | **presence-only cross-art transfer** |
| kinematic-character / separate project bank | unavailable | unavailable | n/a | not measured with this bank | frozen builder refused the art; no bank created |

All 1,020 clean evaluation frames have measured presence outcomes: none were hidden
as unknown or dropped for being difficult. False alarms on platformer are the union
of presence disagreements and applicable frozen-floor crossings; all eight are
presence misses, with zero crossings. Outside results are presence-only: applying a
platformer reference map to another game would be invalid. The result file's strict
`eligibleForLaterConsideration` flag requires complete position evidence as well as
the rate bar; it is false for both pooled sources. This is not a product verdict.

The eight new-route alarms are at frames 36, 37, 72, 73, 145, 146, 246 and 247,
immediately after its four shooting pulses. Four fail masked correlation; the others
fail the frozen body-part confirmation. The values and raw observations are retained.
This is diagnostic information only; no template, score floor or code was changed.
Clean-route effects and legitimate occlusion are not relabelled to improve the rate.

## Seeded changes

These counts are alarm/crossing frames, not independently labelled frame recall.
“Paired” requires a matching clean frame at the same index, and for the new-pixel
column both candidate and clean frames must be new under the fixed hash rule.

| Source / route / patch | Raw event frames | New-pixel event frames / measured | Paired new frames | Meaning |
| --- | ---: | ---: | ---: | --- |
| Platformer coins / hidden-player | 80 absence alarms | 57/97 | 57 | discriminates the hidden variant |
| Platformer coins / sinking | 120 absence alarms | 97/97 | 97 | discriminates sinking |
| Platformer coins / fall-through | 12 position crossings | 0/0 | 0 | every candidate PNG repeats prior data; no new-pixel claim |
| Platformer new / hidden-player | 288 absence alarms | 283/355 | 261 | discriminates the hidden variant; raw pairing is 280 |
| Platformer new / sinking | 360 absence alarms | 355/355 | 333 | discriminates sinking; raw pairing is 352 |
| Platformer new / fall-through | 12 position crossings | 3/12 | 0 | three new candidate crossings, but no new matched clean counterparts at those indices |
| kinematic-character walk + new / invisible | 540 absence alarms | 540/540 | 0 | no discrimination: the robot bank alarms on every clean frame too |
| kinematic-character walk + new / broken | position unsupported | not measured for position | 0 | no applicable floor map or project bank; 122 on-screen presence alarms are not claimed as fall-through detection |

Raw platformer fall-through has 17 on-screen frames on each route, then 103/343
off-screen frames respectively. The new-route new-pixel selection has 12 on-screen
and 343 off-screen frames. Off-screen evidence remains unknown. For the outside
broken patch each route has 61 on-screen frames and 119/299 off screen. A raw alarm
that also occurs on the clean run does not establish seeded-bug detection.
The machine result's seeded `detected` flag means a paired matched-clean event;
its generic `counts.falseAlarmRate` key is an alarm rate for seeded rows. Only clean
rows measure false alarms. The table above separates event and paired evidence.

## What was frozen, and when

The work-log plan was committed locally as `8da75aa` before calibration/capture.
It pins the previously unused public coins route, two new action schedules and the
public outside walk route. It also pins separate outside calibration/validation,
all seeded patches, hash exclusions, denominators, unknown handling and a stop on
unsupported outside calibration. The original plan snapshot and SHA-256 are retained;
results are appended to the log, not substituted for its original plan.

Sensor source and contracts are byte-identical to PR #522 head
`cfb9c9c171d0a433c92732bffb0a39370a83431a`. The exact original 408-template bank has
canonical digest `a40e0e0e49d729eaeb6e58b3686e0102e2573f6407d2f4ddc1a0de1afd515eb8`
and raw SHA-256 `6d646efd35e96306d10ac7e7ab615c2ee63a3d606e95d8a4d441adf7a7d60235`.
Neither changed. No measured pixel entered a bank, mask, threshold or pose catalogue.
New evaluation frames may repeat each other; these frame rates are not claims of
statistically independent trials or a private held-out evaluation.

The first runner launch had an incorrect callback keyword (`progress` instead of
`on_frame`). Python rejected it before entering `from_replay`, opening an evaluation
PNG or producing a score. Only that wrapper call and a signature-binding test were
corrected, and a new execution hash was recorded before the first pixel measurement.
The initial plan, routes, sensor, thresholds and bank were unchanged. The stop log,
original/amended execution manifests and local commit sequence are included.
No result-dependent code change or retuning followed.

## Outside calibration refusal

The pinned public source is `godotengine/godot-demo-projects` commit
`b761b4cd5718a7118f2c95eb55f181d0a5f004f1`, `2d/kinematic_character` (MIT).
Three separate clean training routes (1,080 frames) and a fourth validation route
(360 frames) were captured first, before any evaluation. The frozen builder rejected
`player/player.png` before constructing templates: it requires opaque foreground
AND transparent background. This 16×16 RGBA asset has alpha 255 on all 256 pixels.
Its SHA-256 is `b6af00fd70018d69fbdb87be1a2b712384daed7bbd3387b18e61f127f8c3bb90`.

No project-specific bank or threshold was produced. The art was not edited or padded,
the validator was not bypassed, and a different algorithm was not substituted. The
cross-art 100% result must not be described as performance after project calibration.
Supporting this asset would require another development/calibration cycle, followed
by new evaluation frames if any of these findings inform a change.

## Reproduction and scope

The handover carries the exact bank, frozen manifests, routes, full observations,
trace/replay manifests, raw score components, source-art evidence, arithmetic tests
and an audit script. A separate lossless archive contains ALL **4,980 captured PNGs**
(1,440 outside calibration + 3,540 evaluation, including 1,020 clean frames).
Its availability is stated in the handover README; no cropped samples substitute for
those raw files. The audit checks every PNG hash and recomputes selections, rates,
seed pairings and reference-map proofs without an engine or model call.

Godot 4.7.2 (the previously SHA-512-verified official binary), Linux software rendering,
a private dummy Xorg display, NumPy 2.3.5, Pillow 13.0.0 and one BLAS/OpenMP thread.
Capture uses the harness's `auto` sandbox policy; the missing `xvfb-run` is recorded
as its diagnostic fallback reason. No system policy was changed, and this is not
isolated verdict evidence. The display was stopped after capture. Full-suite work
shared CPU with portions of measurement; no speed or latency claim is made.

`python3 -m unittest discover -s tests -t .`: **3,954 tests OK, 45 skipped**, 445.072 s,
with no `EXPECTRAIL_*` variables in its shell. Four measurement bookkeeping tests pass.
An earlier suite began before the callback correction and is not the final validation.
No live model call, fresh-* content, blind-set content or private held-out repo was
used. Nothing was pushed, posted, opened or dispatched on GitHub. No default verdict
path changed. Numerical data: [template-untuned-result.json](measurements/template-untuned-result.json).
