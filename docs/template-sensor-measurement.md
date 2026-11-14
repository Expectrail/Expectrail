# Template sensor measurements

Evidence: real engine. Algorithm: expectrail.template-ncc/v2.
Frozen bank: `b01dfdeffd3522193ee820d379cd34d72f3570a2abcf88a88ac8afed02d2162a`. Clean tree: `6a273587d64e10a74c0160256cfdc4964f16ed3e93fe7ab178e1bedc5071b280`.
Calibration frames are excluded from these counts; each listed case is a separate replay.

Bank: 1620 templates; calibration status: unmet; threshold 0.9 (floor 0.9).
| Run | Measured object-frames | Matched | Not found | Displaced | Unavailable | Off screen | Agreement | Alarm rate | Mean s/frame | p95 | Max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| clean-smoke | 120 | 96 | 24 | 0 | 0 | 0 | 80.00% | 20.00% | 0.1672582241746568 | 0.28407632680609823 | 0.3130959419941064 |
| clean-combat | 90 | 90 | 0 | 0 | 0 | 0 | 100.00% | 0.00% | 0.15956526340014535 | 0.19850608309934614 | 0.2302281860029325 |
| clean-traversal | 180 | 125 | 55 | 0 | 0 | 0 | 69.44% | 30.56% | 0.15186981098894548 | 0.2094474088407878 | 0.23717793899413664 |
| invisible-player | 120 | 47 | 73 | 0 | 0 | 0 | 39.17% | 60.83% | 0.17270261480795548 | 0.22161950265362976 | 0.2790113590017427 |
| sinking | 120 | 0 | 120 | 0 | 0 | 0 | 0.00% | 100.00% | 0.16248976900751586 | 0.198197693000111 | 0.24933079500624444 |
| fall-through | 17 | 0 | 17 | 0 | 0 | 103 | 0.00% | 100.00% | 0.04125680529953873 | 0.1404101169486239 | 0.18685372799518518 |

Clean-route false-alarm rate: **20.26%** (79 alarms / 390 measured object-frames).
Invisible-player pixel alarms: **73**. Zero alarms does not demonstrate detection.

95% matched on every clean route: NOT MET. Every measured frame under 0.3 s: NOT MET.
Sensor timing includes PNG decoding and matching, excludes Godot capture, bank preparation and checkpoint writes. All per-frame timings survive resume. Accuracy target includes unavailable/off-screen frames in its denominator.

An alarm on a clean run is counted as a false alarm; legitimate occlusion can contribute. Unavailable and off-screen predictions are excluded from rate denominators and shown above. Matched crops do not certify colour, semantic identity, all sprite pixels, or other projects. A collision box is a search hint, not independent visibility truth. No default verdict uses these numbers.

## Run conditions

Godot 4.7.2.stable.official.ed1daf0bf; Linux x86_64, Python 3.12.14, NumPy 2.3.5,
Pillow 13.0.0, private Xorg dummy display and software rendering. The execution container exposes
three logical CPUs and has a two-CPU quota. `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`.
`EXPECTRAIL_SANDBOX=off` was needed to access this private display; harness defaults were not changed.
The full test suite ran concurrently for part of the benchmark, so timing includes shared-CPU contention.

The bank considered 1080 clean training frames from three dedicated routes and
selected 1620 templates including mirrors. A fourth clean validation route
matched 340/360 positives and 0/360
off-player negatives. Calibration status is **unmet**. The threshold stayed at
0.9; it was not lowered to improve measured results. Calibration frames do
not contribute to the measured table above. Measured or bug frames never select templates or thresholds.

The numerical-kernel optimization was tested on clean calibration frames only. Recalibration
produced a byte-identical bank before these final measured/bug captures. The real benchmark was
intentionally interrupted after 30 saved clean-smoke frames and resumed. Saved observations and
per-frame timings were preserved; a second completed resume did not capture or match any frame.
Full before/after test logs, resume checks, frozen bank and underlying observation/trace evidence
are in the handover. The compact bundle includes selected PNGs, not all captured PNGs.

These public routes demonstrate only the rates above. In particular, a larger animation bank
has not established reliable coverage of all clean appearances/backgrounds. The sensor remains
experimental and is not wired into the default verdict. No model was called.

Clean-smoke and invisible-player have **identical engine trace rows and predicted boxes**.
On 49 frames the clean pixels matched and the bug pixels produced an alarm with the same
frozen bank. That demonstrates pixel-only disagreement, not recall against independently labelled
invisible frames. The handover retains the paired frame indices in logs/pixel-only-check.log.
