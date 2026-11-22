# Qualify the bound pause-menu score draft (#744)

## What changed

The approved check format can express an exact integer reading from a named Godot Label at the
end of a specific replay. The harness records only the requested Label paths. The evaluator
requires complete ordered route and coin observations, a positive pickup count, and one readable
bound value before judging the expected score. A legacy approval cannot cover the new assertion.
The public draft expects 5 after the bundled game's rightward pickup route.

## What was run

- The new contract, evaluator, and capture tests demonstrated failures on the original behavior.
- All 15 public Godot 4.7.2 engine diagnostics recorded 464 ordered ticks. Clean and comment-only
  passed 3/3 at 5. Each public defect failed 3/3 at 10 or 0 after five pickups. The frozen player
  read 0 with no pickups and returned needs-review as unexercised in all three runs.
- The focused capture suite with `EXPECTRAIL_ENGINE_TESTS=1` passed 9 tests, including the public
  route and a temporary scene for integer bounds and missing Labels. The split-gate and anonymous
  capture compatibility selection passed 19 tests.

## Not done

The public draft awaits human approval. The capture qualification is an engine diagnostic with
zero PNGs and local sandbox fallback. Rendered text and default release acceptance require
separate evidence.

## Files

- [State and score family inventory](../measurements/721-family-coverage.md)
- [Exact-score measurement and reproduction command](../measurements/744-exact-score.md)
- [Test-spec contract](../../contracts/test-spec.schema.json) and [trace contract](../../contracts/trace.schema.json)
- [Evaluator](../../expectrail/evaluator.py), [gate](../../expectrail/gate/verify.py), and [Godot capture](../../harness/godot/expectrail_harness.gd)
- This work-log entry.
