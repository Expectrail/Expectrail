# Observation timeline (#257)

New captured Godot and Unity replays record where each image belongs in game time.
The trusted gate validates this evidence before evaluating a check. The offline
cases are in [test_observation_timeline.py](../tests/test_observation_timeline.py).

## Capture contract

The harness writes `trace.captureTimeline`: a capture rate and an ordered list of
frames. Each entry has a zero-based `frame`, the last completed physics `tick`, an
inclusive `tickInterval`, a capture `phase`, the captured pixel `viewport` size,
and the world-to-screen affine `transform` `[xx, xy, yx, yy, ox, oy]`:
`screenX = xx * worldX + yx * worldY + ox`,
`screenY = xy * worldX + yy * worldY + oy`.
Coordinates start at the top left and y increases downwards. Bounds use all four
transformed corners. A draw with no new physics tick repeats `[tick, tick]`.
The interval says which physics ticks preceded a draw; it does not claim that
pixels were observed between draws.

Godot records placement at `frame_pre_draw` (`post-physics-pre-draw`). Unity's
one-tick-per-captured-frame harness records it when saving the screenshot after
drawing (`post-draw`), using the camera measured in its last update. The Python
runner joins that map to exact PNG SHA-256 digests and writes `replay.timeline`,
with format `expectrail.observation-timeline/v1`. An invalid capture has a named
`timelineProblem`; it cannot support an accept.

The timeline's `traceSha256` hashes the parsed trace with
`expectrail.contracts.canonical`: sorted keys, compact separators, UTF-8. It is
not the raw file digest in `replay.trace.sha256`. `sourceSha256` hashes the exact
PNG bytes; it is null when materialising engine-only observations without images.
The trusted gate rebuilds the map from the trace and image files and compares it
to the replay's saved map. It does not trust an observer's clock or viewport.

Contracts and synthetic examples:

- [Timeline schema](../contracts/observation-timeline.v1.schema.json) and
  [example](../contracts/examples/observation-timeline.json).
- [Trace schema](../contracts/trace.schema.json) and
  [capture trace example](../contracts/examples/trace-capture-timeline.json).
- [Replay schema](../contracts/replay.schema.json) and
  [replay example](../contracts/examples/replay-timeline.json).

No integer division schedules new observations. In the real 12-tick fixture
recorded for this change, Godot 4.7.2 produced these mappings. The test compares
each image's white sprite pixels with the position at the recorded tick, and
compares both runs' trace and image bytes:

| Physics ticks/s | Capture frames/s | Captured last ticks |
| --- | --- | --- |
| 120 | 60 | 0, 2, 4, 6, 8, 10, 11 |
| 120 | 50 | 0, 3, 6, 8, 11 |
| 50 | 60 | 0, 1, 2, 2, 3, 4, 5, 6, 6, 7, 8, 9, 9, 10, 11 |

These are measurements of this fixture, not a schedule to hard-code. See
`GodotCaptureTimelineTest.test_actual_draws_cover_integral_and_fractional_clocks`.
The Unity 50-tick/50-frame mapping is covered by
`ClockAndContractTest.test_godot_unity_and_fractional_clocks_use_the_recorded_intervals`.
A native Unity capture was **not run** for this change.

## Observation contract and identity

[Observations v1](../contracts/observations.schema.json) adds the timeline and
per-frame observer name/version, source kind/digest, frame, tick and coordinate
space. Each detection also has an `entityId` and sensor name/version. See the
[v1 example](../contracts/examples/observations-v1.json). The frame's `observer`
is distinct from the existing template sensor's per-object `sensor` evidence.
The source is either `image` or `trace`; the engine's ground reference remains
explicitly trace evidence. A visual target cannot be replaced with trace evidence.

Bound engine ids are preserved. Other sensors carry their track id when supplied,
or a local `role:unique` id for a single candidate; these names do not prove
tracking through an occlusion. Multiple candidates for a singular geometric
subject, a `reaches` goal, or a relative-region reference are ambiguous even when
one scores higher. A singular v1 detection without an id is also ambiguous.
The existing `visible` assertion means that some member of a class is visible;
it neither selects a particular member nor gains a new uniqueness requirement.
The existing multiple-surface boundary rule is also unchanged.

For new captures, the SAM writer preserves all raw pixel candidates. A box
rejected by its engine identity filter carries `engineAgreement: false`, producing
needs-review with a disagreement reason; the box is still available to inspect.
An ordinary unfiltered pixel counterexample can still fail while the engine
passes (`TimelineTest.test_screen_counterexample_is_not_replaced_by_engine_position`).
No box is selected merely because it has the highest score.

## Completeness and compatibility

Missing, duplicated or reversed capture records, missing images, duplicate image
names, wrong image dimensions, shifted ticks/digests, and missing required
observations are named measurement gaps. A gap over a required event is
needs-review even if a neighbouring frame contains a witness. There is no
interpolation. Existing explicitly allowed vision sampling still uses
`sampling_plan`; it cannot redefine the capture timeline or relax a check's
coverage obligations. An observer outage cannot pass. An answered absence of a
sprite remains negative evidence, distinct from an unanswered request.

The v0 reader remains available for historical records and injected legacy replay
fixtures. Legacy traces use the historical phase only for integral clock ratios;
a non-integer ratio without a measured map is refused. New stock harness replays
require v1 provenance. There is no user option to remove that requirement.
The engine, SAM, anchored and template observer interfaces emit v1 on new captures;
the template sensor's standalone measurement documents retain their v0 reader.

The separate episode normalizer still conservatively refuses non-integer clock
pairs; this change does not broaden that interpreter. Native Unity compilation
and a real Unity capture still need validation. Existing recorded visual answers
are exact-image matches; this change creates no answers and adds no image tolerance.
