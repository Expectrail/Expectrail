# Pixel checks: generated checks about what is drawn, judged from SAM's answers (#286, first slice)

## What changed
- A new closed shape for a generated check about the screen: `expectrail.pixel-check/v1`
  (`contracts/pixel-check.v1.schema.json`, example `contracts/examples/pixel-check.json`), registered
  with the other v1 records. Its object is a bound role (never free text), its observer is a
  trusted one, its predicate is one of the reference evaluator's four, and it is always
  `model_prior` with no approval field.
- `expectrail/jit/pixel.py`:
  - `parse_candidate` is the writer side. It reads only the closed fields of a model's candidate and
    checks the shape. It refuses a name the project does not bind, a probe not on offer, and a
    predicate or kind of object the observer declares it cannot tell. For `sam-3.1-anchor` that is
    the ground, text and `reaches`, and any object the engine's record gives no position for. It
    also refuses `visual-sensor` (#262) until that is built.
  - `judge` is the reader. It turns recorded `agents/sam_anchor.py` answers into the reference
    evaluator's observations and lets `expectrail/evaluator.py` decide. A frame without both the
    observer and the engine's record is a gap, and a run with a gap is `needs-review`.
  - `keep` applies the keep rule: pass 3 of 3 clean, fail 3 of 3 bug, the same observer setting on
    all six runs. A dropped check gets its reason.
  - `reserve` reserves one SAM image a frame on six runs against the change's cap. A check that
    does not fit is `not-run`.
- The bundled game's bindings (`BUNDLED_BINDINGS`) come from its own node names, until #259's
  project config supplies them.
- Docs: a section in `docs/jit.md` and a table in `docs/contracts.md`.

## What was run
- `python3 -m unittest tests.test_jit_pixel`: 23 tests, OK. They judge the recorded SAM answers in
  `tests/data/sam-anchor/` (runs 43335151089 and 43310237299). The example check passes on the clean
  game's smoke route and fails on `layering_v1`, `layering_v2` and `sinking_v2`. It passes on both
  missing-texture bugs and `sinking_v1`. It is `needs-review` on both physics-fall-through bugs (11
  frames not asked: the player is outside the picture). The same check fails on the clean game
  when SAM was asked with a point (lowest score 0.5) instead of a box.
- The full suite, on the branch (main 32ea4bc plus this change): see the pull request for the count
  and result.
- No model, no observer and no engine was called. Nothing was dispatched and nothing was spent.

## Not done
- No prompt offers pixel checks to the proposer. Nothing calls SAM during a reproduction run.
- No reproduction rate with pixel checks. The recorded answers are seeded bugs of the bundled game,
  not the public bench's screen-only defects, and they hold one answer per frame per build. So the
  tests' three runs are the same answers three times: they test the rule, not SAM's repeatability.
- #286's "Done when" needs a recorded run in which a pixel check reproduces a public screen-only
  defect. That is a live SAM run, for Sean to dispatch.

## Files
- `contracts/pixel-check.v1.schema.json`, `contracts/examples/pixel-check.json`
- `expectrail/contracts.py` (one registry line)
- `expectrail/jit/pixel.py`
- `tests/test_jit_pixel.py`
- `docs/jit.md`, `docs/contracts.md`
- `docs/new-work/2026-11-14-pixel-checks.md`
