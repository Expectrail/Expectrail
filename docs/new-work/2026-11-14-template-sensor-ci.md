# Test the template sensor without imaging packages (#262)

## What changed

The sensor tests now discover without Pillow or NumPy. The stock runner checks the three contract
examples, clean-source refusals, frame and trace digests, frozen bank reuse, checkpoint identity,
saved timings and inconsistent measurement claims. Pixel tests name the missing library when skipped.
The measurement summary links to the full JSON at the reviewed commit and includes its SHA-256.

## What was run

`python3 -m unittest -v tests.test_template_sensor tests.test_template_sensor_v2` ran 40 tests
with both imaging packages, all passing. With neither installed, 16 passed and 24 skipped.
With Pillow alone, 18 passed and 22 skipped. With NumPy alone, 16 passed and 24 skipped.
The full source measurement passed its reader; all six run summaries matched its figures.

## Not done

No new Godot measurement or hosted CI run. The original clean routes had 79 alarms across 390
measured object-frames. This rework does not change the measured threshold or enable any verdict.

## Files

- `agents/template_observations.py`
- `agents/template_sensor_bench.py`
- `docs/template-sensor.md`
- `docs/template-sensor-measurement.json`
- `docs/new-work/2026-11-14-template-sensor-ci.md`
- `tests/test_template_sensor.py`
- `tests/test_template_sensor_v2.py`
