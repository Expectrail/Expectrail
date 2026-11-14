# NumPy template sensor, clean calibration and resumable measurements (#262)

## What changed

- Use NumPy integral-image area samples and batched matrix multiplication for multi-scale NCC
  inside the engine-predicted region. Preserve the observer interface and `agreeing` filter.
- Examine every eligible frame from three dedicated clean calibration routes; automatically select
  distinct appearances and their horizontal mirrors. A fourth clean route alone calibrates the
  threshold against player positives and off-player negatives. Never lower the 0.90 floor; record
  an unmet calibration explicitly. Freeze the bank before any measured or bug capture.
- Persist capture hashes, frozen-bank identity, per-frame observations and original sensor timing
  atomically. `--resume` verifies inputs/hashes and continues without recalibrating or repeating
  completed frames. Record progress per capture, every 30 measured frames, and per completed run.
- Extend bank, observation and measurement contracts with source/mirroring/calibration metadata,
  timing and target outcomes; ship examples, writers and readers together. NumPy and Pillow are
  development dependencies; the opt-in repository observer does not alter the verification wheel.
- Retain limits on colour, text/identity, animation correctness, occlusion, background similarity
  and out-of-region detection. Missing evidence is not a partial positive answer. No default
  verdict, SAM adapter, approved spec/approval, protected source, source game or workflow changes.

## What was run

Required fetch of `c169a5e0da304773587304ed47bc8aabcec80da7` succeeded before testing.
Base main: `c8a90427ea9a043f1e11e6c630631e441597bcf9`.

Fresh before on the frozen **previous handover**: **3,094 tests**,
`FAILED (failures=3, errors=3, skipped=31)`.
After this revision: **3,101 tests**, `FAILED (failures=3, errors=3, skipped=31)`.
Exact failure/error names and kinds are unchanged; no new failures or skips. `VALIDATION.json`
and both full logs retain the comparison. For the cumulative main patch, the first handover's
untouched-main baseline (3,070 tests, the same six failure/error names and 31 skips) is additionally
included as `logs/original-main-before.log`; it is not presented as a fresh run.

- ERROR: `setUpClass (tests.test_event_input.EventInputTest)`
- ERROR: `setUpClass (tests.test_pause_input.PauseInputTest)`
- ERROR: `test_a_real_fix_is_accepted_with_the_private_sessions_mounted (tests.test_web.FixLoopTest.test_a_real_fix_is_accepted_with_the_private_sessions_mounted)`
- FAIL: `test_its_own_tests_pass_and_every_body_it_sent_is_in_the_contract (tests.test_runit_edge.EdgeFunctionTest.test_its_own_tests_pass_and_every_body_it_sent_is_in_the_contract)`
- FAIL: `test_a_bug_its_checks_cannot_see_is_not_detected_without_sam (tests.test_web.FixLoopTest.test_a_bug_its_checks_cannot_see_is_not_detected_without_sam)`
- FAIL: `test_without_the_private_sessions_nothing_is_accepted (tests.test_web.FixLoopTest.test_without_the_private_sessions_nothing_is_accepted)`

The two input classes lack `xvfb-run`; the Node edge test expects a different summary format;
the same three web fix-loop cases fail on the frozen baseline. This suite is not green here.
The architect must validate on Linux and satisfy AGENTS.md before opening a PR.

Focused sensor/Unity agreement/evaluator/package run: **87 tests passed**, including all
**31 sensor tests** (24 from v1 plus seven new calibration/NumPy/resume tests).
The final full suite includes the matrix-multiplication kernel, thread-setting provenance and
updated contract examples. An earlier after-run also had the same six failures; it is retained
as development evidence and is not the final comparison.

Real Godot 4.7.2 runs on Linux used a private Xorg dummy display, software rendering, one
BLAS/OpenMP thread, NumPy 2.3.5 and Pillow 13.0.0. Some runs shared a two-CPU quota with tests.
The frozen bank has 1620 templates from 1080 clean training
frames; separate clean validation did not lower the threshold. Final measured/bug captures followed
bank freezing. The bank stayed byte-identical through the numerical-kernel optimization.

| Run | Matched / requested frames | Mean s/frame | p95 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| clean-smoke | 96/120 | 0.1673 | 0.2841 | 0.3131 |
| clean-combat | 90/90 | 0.1596 | 0.1985 | 0.2302 |
| clean-traversal | 125/180 | 0.1519 | 0.2094 | 0.2372 |
| invisible-player | 47/120 | 0.1727 | 0.2216 | 0.2790 |
| sinking | 0/120 | 0.1625 | 0.1982 | 0.2493 |
| fall-through | 0/120 | 0.0413 | 0.1404 | 0.1869 |

At least 95% matched on **every** clean measured route: **NOT MET**.
Every measured frame below 0.3 seconds: **NOT MET** (conservative maximum-frame test).
Clean false alarms: **79/390 = 20.26%**.
Invisible-player pixel alarms: **73**.
Of these, **49** are paired clean-matched to bug-alarm frames with identical engine trace
rows/predicted boxes and the same frozen bank: pixel-only disagreements, not a labelled recall rate.
Calibration validation: **340/360 = 94.44%** positives,
**0/360** off-player negatives, status **unmet**.
Threshold **0.9**, unchanged from the 0.90 floor.

The real benchmark was interrupted after 30 durable clean-smoke frame checkpoints, resumed, and
then resumed again after completion. Saved observations, timings and bank bytes survived unchanged.
The completed resume made no captures or matches. Report/trace/observation/checkpoint evidence is
in the handover; docs/template-sensor-measurement.md and .json publish the rates and conditions.
Sensor timing excludes engine capture, calibration and checkpoint writes. See the report for all
unavailable/off-screen counts and denominators. No measured/bug input tuned calibration.

## Not done

Any unmet targets above remain unmet; the sensor is not ready for a default verdict. No threshold
was lowered. No claim covers other games, all animation/background appearances, colour, semantic
identity or perfect hidden-frame detection. Native macOS and other engines were not measured.
Sean still decides default integration. No paid model calls, approvals, commits, pushes or GitHub
writes. Protected files and bundled source games were not edited. The architect must obtain the
green Linux suite required by AGENTS.md before opening the PR.

## Files

- `agents/template_observations.py`
- `agents/template_sensor_bench.py`
- `contracts/examples/observations-template.json`
- `contracts/examples/template-bank.json`
- `contracts/examples/template-measurement.json`
- `contracts/examples/test-spec-template.json`
- `contracts/observations.schema.json`
- `contracts/template-bank.schema.json`
- `contracts/template-measurement.schema.json`
- `docs/new-work/2026-11-13-template-sensor.md`
- `docs/template-sensor-measurement.json`
- `docs/template-sensor-measurement.md`
- `docs/template-sensor.md`
- `requirements-dev.txt`
- `tests/test_template_sensor.py`
- `tests/test_template_sensor_v2.py`
