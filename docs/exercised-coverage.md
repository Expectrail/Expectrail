# Exercised coverage (#256, #357)

A check can pass only after its obligation was exercised. Coverage is evidence about the existing
assertion; it does not change a boundary, tolerance, object prompt, or approval. No existing approved
spec file was edited for this change. Adding obligations to an approved spec changes its content
and needs a person's review; never copy its old approval onto a changed spec.

The optional `coverage` object in [test-spec/v0](../contracts/test-spec.schema.json) accepts:

- `minFrames`: minimum distinct judged frames.
- `minFraction`: minimum judged share of the window, rounded up. Both minima apply when both
  are given. Frames excluded by `requireOverlap` do not count as judged.
- `routes`: names of the routes this spec applies to. Every named route is required; selecting
  only a subset cannot produce an accept. Other routes are `not-applicable`, not passing checks.
  Without this field, the spec applies to every selected route.
- `reached`: checkpoints, all of which must occur at or after `fromTick` (default zero). `on-floor`
  requires the bound player's `onFloor` flag to be true. `position-region` requires the bound
  player's point in an inclusive `[x0, y0, x1, y1]` world-coordinate box. `coin-count-change`
  requires an explicit coin count different from the first eligible tick. An explicit empty coin
  list is zero; an absent list is unknown. Checkpoints are engine facts about the route, not claims
  that the visual observer independently measured them. Missing checkpoint data needs review.

See [the draft example](../contracts/examples/test-spec-coverage.json). It has no approval.

The default minimum is two judged frames for a multi-frame window. An explicitly one-frame window
requires one; an existential `reaches` assertion needs its witness frame unless stronger obligations
are declared. No default fraction is added. Existing missing-object rules still apply: meeting the
minimum cannot turn a missing object into a pass. A concrete observed violation still fails, even
if coverage elsewhere is incomplete.

A standalone evaluator given neither route bounds nor a bounded window can judge only the supplied
frame domain (including a one-frame domain). It cannot infer an entire route from those observations.
The gate independently knows the route's ticks and the adapter's capture rate. It requires every
route tick and every frame of the applicable window, under **both** `engine-only` and `both`.
As before, the window is intersected with the declared route's duration; an empty intersection is
not exercised. An engine record that stops early cannot redefine that duration. Duplicate tick
numbers cannot fill a gap. An explicitly lower `minFrames` never bypasses the gate's completeness
check. The `reaches` visual observer may supply its witness instead of every observed frame, but
all route ticks and captured window frames are still required.

This is why #357 is fixed in the gate's `engine_gap`, before either rule can return a pass: the gate
has the independent route and capture bounds, while the standalone evaluator has observations.
A short record says, for example, `not-exercised: the engine's record has 20 of 240 ticks ...`.
The saved evaluator verdict is also needs-review; no passing sidecar is left behind that gap.

The result remains `needs-review` for unmet coverage, with a reason beginning `not-exercised` and
counts. Its `coverage` block distinguishes `not-reached` (the required checkpoint was observed but
never happened), `not-exercised` (too few triggers or evaluations), and `insufficient-observation`
(data is missing). An out-of-scope route has result and status `not-applicable`; it counts neither
as a pass nor as a required check. A suite with no required checks still needs review. Findings
readers recompute applicability from the spec's recorded route scope, required counts, missing
required routes, observer combination, and the decision. The page and comment say “not applicable”.

The geometry evaluator and `expectrail.trace.evaluator` share `expectrail.coverage.evidence_result`,
extracted from the trace interpreter without changing its ordering: counterexample → fail;
unknown applicability → insufficient observation; no applicable trigger or too few evaluations →
`not_exercised`; incomplete required window → insufficient observation; otherwise pass. The
geometry verdict's `coverage.semanticResult` retains those meanings. `not-reached` is the explanation
for a required trigger that never occurred, not another kind of success.

Visual sampling uses the unchanged assertion predicate to choose which frames to inspect, never
as its final covered verdict. Explicit frame-count/share obligations select every frame, including
for `reaches`; the final evaluator and gate still decide coverage. No model call is part of the
coverage calculation.

For standalone evaluation with route-scoped obligations or checkpoints:

```sh
python3 -m expectrail.evaluator --spec spec.json --observations observations.json \
  --route smoke --trace trace.json --out verdict.json
```

`not-applicable` exits 2 here, not 0. The gate's aggregate may accept when all required checks pass,
while excluding nonapplicable rows. Old records without the new fields remain readable. Records
using the new scope/result require this change's writer and reader together; older closed-schema
readers refuse unknown fields/results rather than silently accepting them.
