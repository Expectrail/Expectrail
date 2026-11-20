# The six counting rules are applied to pixel checks, reported but not counted (#271, #286)

## What changed
Pixel checks live in a run record's `pixelChecks`, and the six-rule assessor of #271 only read
`proposed`/`validity`, so every screen-only check was advisory with no reason given.
`expectrail.jit.assess.pixel_counting` now recomputes the six rules for each pixel row from its own runs
(never its `status` or `outcome`), with a relevance binding for drawn objects and pixel predicates
(`pixel_relevant`: the report must name both the object and the behaviour; the check's statement is
never read). `python3 -m expectrail.jit.counting pixel-bench` writes the page
`docs/measurements/271-pixel-counting.md` from the committed stand-ins: 6 pixel checks, 0 counting.
`counting.make` does not call it, so no pixel row reaches `decide`. `docs/jit.md` describes each rule
for a pixel row.

## What was run
- `python3 -m unittest tests.test_jit_pixel_counting`: 20 tests; 19 failed before the change (no
  `pixel_counting`), all 20 pass after.
- `python3 -m expectrail.jit.counting pixel-bench --records bench/jit/stand-in --out docs/measurements/271-pixel-counting.md`:
  `{"records": 2, "checks": 6, "counting": 0, "advisory": 6}`.
- Full suite: see the pull request.
- No replay, no observer, no model call, no dispatch. Nothing spent.

## Not done
Pixel rows are not in the `expectrail.generated-counting/v1` envelope and do not reach the gate's
`decide` or its visual-evidence policy. No pixel check has been produced by a model inside the trusted
boundary, so none can count yet. The relevance lists are small and have false negatives (stated in
`docs/jit.md`).

## Files
- `expectrail/jit/assess.py`
- `expectrail/jit/counting.py`
- `tests/test_jit_pixel_counting.py`
- `docs/measurements/271-pixel-counting.md`
- `docs/jit.md`
- `docs/new-work/2026-11-18-pixel-six-rules.md`
