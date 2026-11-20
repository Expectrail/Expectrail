# #262 Done when audit at main d877ddb

Issue [#262](https://github.com/Expectrail/Expectrail/issues/262), its six comments,
and merged [#522](https://github.com/Expectrail/Expectrail/pull/522) and
[#563](https://github.com/Expectrail/Expectrail/pull/563) were read before this run.
Base: `d877ddb647161e4af28aa554e7886d91e1b83f5b`. The claim and branch were already
provided. No GitHub write was made.

| Done when case | Exact evidence on main before this patch | Closeout evidence |
| --- | --- | --- |
| Clean and seeded-bug builds: publish agreement with the engine on clean frames | `docs/template-sensor-measurement.json`, `runs[*].summary.agreementRate`, records the #522 public tuning corpus (390 clean frames, zero alarms). `docs/measurements/template-untuned-result.json` and `docs/template-sensor-untuned-measurement.md` record the separate #522-bank evaluation: new-route 8/341 false alarms (2.35%). These predate the current bank recipe's enemy additions. #563 reports some successful clean probe observations, explicitly without a probe false-alarm measurement. | [Generated closeout table](template-sensor-closeout.md): current main's 556-template bank, two pre-registered evaluation routes, every frame. Raw and new-pixel agreement rates, false alarms and unknowns have explicit denominators. All three existing seeded builds are recorded too. |
| Flag invisible-player from pixels alone | `tests.test_template_sensor.SensorTest.test_invisible_pixels_fail_even_with_identical_engine_rows`; `tests.test_template_foreground.ForegroundTest.test_empty_pixels_fail_with_identical_engine_rows_and_no_network`. #522's measurement records 49 paired detections on tuning frames; the untuned report records 261 paired new-route events and 57 on coins. These are alarm counts, not labelled absence recall. | The current bank produces 73 matched-clean/new-pixel absence alarms. Both runs have identical complete trace rows and identical body/camera/player-visible search inputs. Hidden PNGs are evaluated with the **clean trace**, same bank and spec. `tests.test_template_closeout.PixelOnlyProof.test_same_trace_and_bank_flag_hidden_pixels_without_a_visibility_hint` also checks the causal distinction on synthetic pixels. |
| Measure and publish false alarms on clean routes | Already measured on main: 79/390 → 0/390 on public tuning frames (#522); independently 8/341 (2.35%) on one untuned route, 0/97 on coins, 8/438 pooled. The outside robot-bank arm alarms on 540/540 clean frames; its own bank was unavailable. `tests.test_template_untuned_measure.MeasurementCountsTest` covers exclusions/unknown arithmetic. | Current bank: 2/115 and 2/112 false alarms on new PNGs, pooled 4/227 (1.76%). No missing or off-screen clean frames. The preceding worse route and outside results remain published and are not replaced. |

The requested scoped diagnostic Done when is met. **Closes #262** is appropriate for
this delivered measurement, with the limits below retained. It does not establish a
release-quality observer, cross-game transfer or a universal under-2% rate.

## What remains outside this closure

The sensor stays opt-in. The existing explicit JIT observer from #563 is unchanged;
this patch adds no default gate use. The earlier 2.35% independent route remains a
counterexample to a blanket under-2% claim. The new sample is small and frames are
correlated. No model/live JIT dispatch or hosted sensor trial was run. No rate for
enemy detection or facing is measured here, although current main calibrates those
templates alongside the player. No current-ground segmentation, arbitrary colour,
text, identity, distant search or other-game capability is added.

The original invisible-player fixture changes draw order (`z_index = -6`), so it is
not fully absent in every frame. The published counts are events, not frame recall.
The engine provides the search hint; only the pixel difference supplies the absence
alarm in the equal-trace comparison. Fall-through uses pixel positions crossing a
frozen clean floor map; it is not labelled as invisibility.

## Repeat and verify without models

Install the same pinned Godot 4.7.2 and a local display/Xvfb, NumPy and Pillow. The
handover's companion archive includes complete calibration/evaluation captures, the frozen bank, original
plan, source hashes, every observation/region proof and the execution scripts. From
this checkout, recompute every figure without rerunning detection:

```sh
python3 -m tools.template_sensor_closeout --evidence /path/to/evidence \
  --out /tmp/template-closeout-result.json --markdown /tmp/template-closeout.md
```

The reader checks every PNG, trace, route, ordered patch and bank digest, all frozen
sensor source files, historical/calibration exclusions, and the counting-function hash
recorded before matching. It recomputes region proofs, summary arithmetic, paired
frames and the pixel-only cue identity. Changed evidence is a named stop.

For new rendering, use the handover's `capture-portable.py` and `measure.py` with a
new `--out` folder populated with the frozen plan and prior hash list; copy its
`patch-files/tools/template_sensor_closeout.py` counting snapshot too. No automatic
fetch, model fallback, candidate calibration or threshold adjustment occurs. Matching
and source hashes must agree before treating a regeneration as the same recording.
A different renderer is a different recorded run, not a matching substitute.
