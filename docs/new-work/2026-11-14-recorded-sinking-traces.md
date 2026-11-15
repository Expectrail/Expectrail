# Test the ground check on recorded sinking traces (#259)

## What changed

A unit test reads two complete smoke-route traces from the bundled game. Godot recorded the
clean game and a copy with `bugs/sinking/v1.patch`. The test decompresses the records, passes
them through `from_trace_synthetic` and judges the existing ground spec with `evaluate`.

The two gzip files contain the harness's original JSON bytes. To reproduce the captures from
this checkout with Godot 4.7.2 installed, run this from the repository root:

```sh
python3 - <<'PY'
from pathlib import Path
from harness.run import run
for name, patch in [('clean', None), ('sinking_v1', Path('bugs/sinking/v1.patch'))]:
    run(Path('harness/routes/smoke.json'), Path('runs/recorded-sinking', name).resolve(),
        patch=patch, capture_frames=False)
PY
```

## What was run

- `python3 -m unittest -v tests.test_recorded_sinking` failed on #430's rejected head
  `6aecc16`. Sinking v1 passed the ground check there. On the merged observer it failed at
  frame 8 and the clean trace passed all 120 frames.
- The CI sinking verdict calculation, using the clean level's reference surfaces, gave
  `{'clean': 'pass', 'sinking_v1': 'fail', 'sinking_v2': 'pass'}` on fresh headless traces.
- The three base-config gate tests from #430 passed. They cover the candidate adding a capture
  rate, changing the player binding and supplying an invalid config.

## Not done

The local recordings have no rendered frames. The rendered seeded-bugs job was not run locally.
The host refused Bubblewrap's network namespace, so the local harness recorded its diagnostic
fallback. The sandboxed seeded-bugs job passed on the merged #430 head.
[Hosted run](https://github.com/Expectrail/Expectrail/actions/runs/43646873203/job/132606520068)

## Files

- `tests/test_recorded_sinking.py`
- `tests/data/sinking/clean.json.gz`
- `tests/data/sinking/sinking_v1.json.gz`
- `docs/new-work/2026-11-14-recorded-sinking-traces.md`
