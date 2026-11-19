# Pixel checks are carried in the counting envelope and can be their own visual evidence (#271, #286)

## What changed
`counting.make` now puts one row per pixel check (`assess.pixel_counting`) after the trace rows in the
`expectrail.generated-counting/v1` envelope. Before this, it carried trace rows only, so a screen-only
check could never reach `decide` however many rules it met. Each pixel row has `kind: "pixel"`, its
`observer` and `setting`, and runs in the pixel vocabulary (`pass`, `fail`, `needs-review`). Rows are
still recomputed from the source run on every read, so a changed row or run is refused. A pixel check
may not reuse a trace check's id.

Contracts change together: the envelope schema and the gate record's `countingChecks` (in
`contracts/findings.schema.json`) take the same two closed row shapes, now up to 12 rows (8 trace, 4
pixel). New example: `contracts/examples/generated-counting-pixel.json`, made by `counting.make` from the
enemy stand-in with no trust, so nothing counts.

The gate's visual-evidence policy (`record.decide`): under `both`, a counting trace row is the engine's
record alone and still keeps the decision at needs-review. A counting pixel row is its own per-check
visual evidence, because its runs are a trusted observer's verdicts over frames where the engine's
record also places the object. It can demonstrate a repair. It still never clears a change alone, and
any failure still rejects. The repair words name a pixel check as such.

The pressure dispatches replay trace checks only. If a pixel check counts, `pressure.frozen` now stops
(`pixel-checks-not-replayed`) instead of quietly replaying fewer checks than count.

## What was run
- `python3 -m unittest tests.test_jit_pixel_envelope`: 18 tests. Before the change, 8 failed and 4 errored.
  After it, all pass.
- `python3 -m unittest tests.test_jit_pixel_envelope tests.test_jit_pixel_counting tests.test_jit_rules tests.test_contracts`:
  88 tests, OK, 1 skipped.
- `python3 -m expectrail.jit.counting pixel-bench --records bench/jit/stand-in --out docs/measurements/271-pixel-counting.md`:
  `{"records": 2, "checks": 6, "counting": 0, "advisory": 6}`. Only the page's wording line changed.
- Full suite: see the pull request.
- No replay, no observer, no model call, no dispatch. Nothing spent.

## Not done
No pixel check has been produced by a model inside the trusted boundary with a signed source receipt, so
none counts on any committed record. The pressure dispatches cannot replay pixel checks yet. A pixel row
is not bound to the record's named visual observer, only to its own trusted observer.

## Files
- `contracts/generated-counting.v1.schema.json`
- `contracts/findings.schema.json`
- `contracts/examples/generated-counting-pixel.json`
- `expectrail/jit/counting.py`
- `expectrail/jit/assess.py`
- `expectrail/jit/pressure.py`
- `expectrail/gate/record.py`
- `tests/test_jit_pixel_envelope.py`
- `tests/test_jit_pixel_counting.py`
- `docs/measurements/271-pixel-counting.md`
- `docs/jit.md`
- `docs/new-work/2026-11-19-pixel-envelope.md`
