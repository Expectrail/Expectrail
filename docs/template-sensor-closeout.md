# No-model sensor closeout measurement (#262)

Generated from the frozen run record. No model calls, detector changes or verdict-readiness claim.

[Machine record](measurements/template-closeout-result.json) · [Pre-measurement plan](measurements/template-closeout-plan.json).

| Clean route / selection | Agreement with engine search prediction | Clean false alarms | Unavailable / off-screen |
| --- | ---: | ---: | ---: |
| clean-a / raw | 118/120 (98.33%) | 2/120 (1.67%) | 0 / 0 |
| clean-a / newPixels | 113/115 (98.26%) | 2/115 (1.74%) | 0 / 0 |
| clean-b / raw | 118/120 (98.33%) | 2/120 (1.67%) | 0 / 0 |
| clean-b / newPixels | 110/112 (98.21%) | 2/112 (1.79%) | 0 / 0 |
| **Pooled / raw** | **236/240 (98.33%)** | **4/240 (1.67%)** | 0 / 0 |
| **Pooled / newPixels** | **223/227 (98.24%)** | **4/227 (1.76%)** | 0 / 0 |

Agreement means a pixel match whose box overlaps the engine prediction under the existing IoU rule. False alarms are the once-per-frame union of absence/displacement and applicable frozen-floor crossings. Unknown/off-screen frames are separate, never passes. New pixels exclude historical and calibration hashes, without looking at their scores. Frames are correlated samples, not independent trials.

| Seeded build | Raw event frames / measured | New-pixel event frames / measured | Matched-clean paired events: raw / new | Unknown/off-screen: raw; new |
| --- | ---: | ---: | ---: | --- |
| invisible-player | 80/120 | 75/115 | 78 / 73 | 0/0; 0/0 |
| sinking | 120/120 | 115/115 | 118 / 113 | 0/0; 0/0 |
| fall-through | 12/17 | 3/11 | 12 / 3 | 0/103; 0/103 |

These are alarm/crossing frames, not independently labelled frame-level recall. Fall-through uses visible pixel boxes crossing the clean floor reference; an off-screen player is unknown.

## Pixel-only invisible-player proof

The paired runs have identical search predictions: **True**, identical engine cue rows: **True**, and identical complete trace rows: **True**. The hidden PNGs were judged with the **clean trace**, the same frozen bank and the same spec. Thus pixels supply the distinguishing absence evidence. The engine still supplies a bounded search hint; this is not unconstrained full-screen detection.

## Frozen provenance and limits

Base `d877ddb647161e4af28aa554e7886d91e1b83f5b`; plan SHA-256 `87f75acc7ca0032de92342ca70ebd33f6c0f3526dc6edf63bc9438577e547cb1`.
Bank `a89f0a15ddd3c41925f514e7829c99249d82c3962fddaa5a5162dc11848d081e`, 556 templates, algorithm `expectrail.template-foreground/v3`, threshold 0.9; calibration `met`.
The machine record contains every frame status/PNG digest and the hashes/paths of its replay, trace, observations and region proof. The accompanying handover contains these source records and regeneration commands.

This small, pre-registered bundled-game sample does not replace the earlier untuned-route 2.35% false-alarm finding, prove cross-game transfer, or make the sensor eligible for a release verdict. The existing opt-in JIT wiring is unchanged. No hosted dispatch, live model call, approval, game-source edit or workflow edit ran.

Done when evidence complete for this scoped diagnostic sensor: **True**.
