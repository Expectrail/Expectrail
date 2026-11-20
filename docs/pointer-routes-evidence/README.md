# Pointer-route contract evidence

This records the route-contract half of #259, not a successful Breakout retrial.
The source main is `ed6f296` (full commit in the handover's BASE_COMMIT.txt).
The prerequisite tree, after applying Part A and the historical Part B trial,
is `d48f98e2761bbe2431d7995fe34cc6925ce16826`.

[Parity comparison](parity-comparison.json) links to every before/after check.
Each check folder also contains its actual trace and replay metadata. All eight
trace pairs are byte-identical. Captures used Godot 4.7.2, Mesa llvmpipe LLVM
19.1.7, Xvfb and sandbox off. They are engine-regression evidence, not an isolation
or vision claim. The existing shared judge used `both` without a visual observer.

The outside source pin is `b761b4cd5718a7118f2c95eb55f181d0a5f004f1`, from
`godotengine/godot-demo-projects` (MIT), using the paths, routes and patches in
[the existing trial list](../../tests/outside/projects.json). No game sources
are vendored here. Bundled smoke uses the existing fall-through patch. The exact
reproduction script and invocation logs are in the handover; its local paths
must be set to the reviewer's checkout/tool/source paths.

[Pointer tests passing](green-pointer.txt) ran all 17 pointer tests and 9 unchanged existing event-input tests, with the real pinned
engine and a display. [Default-PATH run](offline-and-named-skips.txt) names the
missing pinned engine when only another version is on PATH. The real tests assert
three identical trace byte strings in each of headless and rendered mode, then
assert the click, movement, held right button and release effects at their ticks.

[Red tests](red.txt), [catalog refusal red](red-catalog.txt) and
[rendered red](red-rendered.txt) ran before the implementation. The original red
run's two preflight cases named an incorrect fixture directory; their path was
corrected without changing assertions. [Corrected preflight red](red-preflight-corrected-fixture.txt)
runs them against the prerequisite harness loaded from its Git tree. They then
pass on the new runner. No existing tests or assertions were changed.

[Related tests](related-corrected.txt) cover the existing contracts, action
routes, episode evaluator, onboarding and harness. [Before](full-before.txt), [after](full-after.txt) and
[comparison](test-comparison.json) record the full-suite result. The initial
disk-exhausted attempt is in the handover only and is not used as the baseline.

Published path spellings were redacted in the registry follow-up; [evidence handling](../outside-trials/breakout-ci/evidence-notes.md) explains the placeholders and original handover records.
