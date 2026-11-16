# Local template sensor (#262)

`agents.template_observations.TemplateObserver` is an **opt-in experimental observer**.
It reads pixels without a model, network request or API key. No default observer,
verdict rule, approval, or source game is changed. This checkout-only sensor is not
added to the verification wheel. See [the measurement](template-sensor-measurement.md)
for the reproduced baseline and paired public results.

## Foreground witnesses

The explicit `--foreground-art OBJECT=PATH` option selects
`expectrail.template-foreground/v3`. It requires a separately trusted clean game,
whose tree digest is pinned before calibration. An unpatched candidate is not
therefore trusted. The caller selects the art; this code never approves it.

A clean RGBA asset supplies its opaque RGB palette (alpha at least 250, 2–4096
colours, with transparent background). Palette membership selects foreground pixels
**on clean training crops only**. Both RGB bytes and binary masks are frozen with
hashes. Changing trees, sky and ground inside the collision rectangle no longer
participate in the same way as player pixels. This is an art-specific mask, not
semantic segmentation: scenery sharing the palette can still cause ambiguity.

Masked luminance NCC proposes positions in a bounded search. The 16×16 pooled grid
uses bins with at least 95% foreground, a minimum of 32 usable bins and luminance
contrast 8. Up to 32 distinct template/scale proposals receive full-resolution RGB
confirmation. A match needs NCC, total foreground coverage and each of four horizontal
parts above the threshold. RGB tolerance is 2; a one-pixel neighbourhood and eroded
mask allow raster phase differences. These are recorded settings, not probabilities.
A missing frame is never filled from adjacent frames. Missing parts or same-luminance
wrong-colour lookalikes fail the offline regression tests.

Search settings remain margin 16 px, stride 1, scales 0.75/1/1.25 relative to the
predicted size, agreement IoU 0.5 and threshold floor 0.90. Ties are deterministic,
with scores rounded to seven decimal places for ordering. Every eligible clean
training frame is considered; distinct masked appearances are selected at correlation
0.995 and mask IoU 0.9, then mirrored. More than 2,048 templates is a named error.
The bank is frozen before measured or seeded cases are read. Candidate pixels never
supply masks, thresholds, new templates or pose registration.

Three dedicated clean routes cover walking, jumping and firing in both directions.
A fourth separate clean route supplies positive and displaced off-player negative
validation windows. Calibration may raise the requested threshold, never lower it;
it records `unmet` unless at least 95% of positives and at most 1% of negatives match.
The algorithm was developed on public regression results: the reported improvement
is tuning evidence, not private held-out or cross-game validation.

## Optional clean pose catalogue

Some valid animation poses are absent from captured training routes. The optional
`--foreground-catalogue PATH` adds caller-selected poses directly from the same
trusted RGBA sheet. The [catalogue example](../contracts/examples/template-foreground-catalogue.json)
names the sheet, grid, pose indices and scene reference hash for the bundled clean
game. It is configuration, not an approval. All paths must stay inside that clean tree.

Registration uses only a clean capture anchor. Sparse colour correspondences propose
translations for fixed nearest-neighbour scales 1/1.5/2/2.5/3/4; a full foreground RGB
comparison must agree by at least 98%. There are no hardcoded collision/sprite offsets.
The bank freezes the RGBA bytes, scene/art provenance, anchor hash, fitted scale and
offset. Derived entries have `kind: approved-art-pose`; they are not misrepresented
as captured frames. Readers reconstruct every derived pose from the frozen sheet
and verify its clean anchor agreement. Runtime observation does not need source files.

## Prediction, pixel evidence and unknowns

Godot's `body` collision rectangle is a search hint, transformed using the next tick's
camera `view` (last-tick fallback at the end), matching capture timing. All four
corners are transformed. Fractional predictions and rounded calibration crops remain
separate; no bundled-game player dimensions are copied. Capture fps must divide
physics ticks. Missing/duplicate rows or cameras are never interpolated.

Coordinates are `[left, top, right, bottom]`, half-open, origin top left, y down.
Boxes locate the calibrated rectangle, not the whole sprite silhouette. Every frame
retains prediction, searched region, raw match, score, template frame, scale and RGB/NCC
components. Object detections contain only agreeing matches. Status is one of:

- `matched`: sufficient pixel evidence and overlap with the prediction.
- `not-found`: readable pixels searched, no confirmed template above threshold.
- `displaced`: confirmed pixels disagree with the prediction or caller's filter.
- `unavailable`: image, trace row, camera or usable search is missing.
- `out-of-frame`: prediction not entirely on screen; partial crops are unsupported.

`TemplateObserver.look(spec, run, keep=...)` and `describe()` implement the existing
observer interface. `look` raises `NoAnswer` for incomplete/unsupported evidence,
including any unavailable/off-screen requested frame. Raw CLI observations retain
unknown rows for diagnosis; an empty detection list on those rows is not measured
absence. `summarize` checks component scores and object detections before counting.
An optional `agreeing` callback may remove detections, never add them.

Additional named sprites require explicit prediction maps during calibration and
observation. Every requested object needs its own clean template; missing objects
are never replaced with engine-only detections. Prompts bind names, not semantics.
For objects the game has many of, the prediction map is the engine's own logged box
of each one (`enemyBoxes`, `projectileBoxes`; `object_predictions`), and
`calibrate_routes(..., objects=...)` records each object's validation apart from the
player's under `calibration.objects` (docs/jit.md, "The enemy"). The enemy's clean
captures are also labelled with the way the engine moved it (`heading`), and its facing
is validated as drawn and mirrored in place (`calibration.objects.enemy.facing`; docs/jit.md,
"Which way the enemy faces").
The sensor refuses colour/text semantics even though RGB witnesses help identify art.

## Frozen ground regions

The v3 benchmark also measures an observed player crossing regions frozen from the
**trusted clean calibration trace** (`levelSurfaces`). It uses detected pixel boxes
and the candidate camera, never candidate body/ground/surface rows to establish the
floor boundary. For positive, axis-aligned camera transforms, it checks overlap with
a region's upper boundary. A region arms only after the player is above it within
20 screen pixels, then reports subsequent below-boundary frames. The 20 px tolerance
matches the existing public ground specification. Walking under an overhead platform
does not arm that platform from below. Missing pixels, camera or reference remain
unavailable, and reported crossings are recomputed from the stored proof by readers.

This is a frozen reference-map check, **not segmentation of current floor pixels**.
It cannot certify removed/moved floors, a player already below terrain on the first
frame, unsupported camera transforms, or gaps without pixel evidence. The benchmark
reports region crossings separately from absence: a visible player below a floor is
not invisible. No new region result is wired into a default verdict.

## Commands and reproducibility

Install NumPy and Pillow locally. The recorded run used NumPy 2.3.5 and Pillow 13.0.0.
Pixel tests skip by name when Pillow or NumPy is unavailable; metadata tests still run.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m agents.template_sensor_bench \
  --godot /absolute/path/to/pinned/Godot \
  --foreground-art player=player/robot.webp \
  --foreground-catalogue contracts/examples/template-foreground-catalogue.json \
  --out /tmp/expectrail-template-foreground
```

Use the pinned Godot version from the measurement and a display for new captures.
`--resume` reuses only captures, bank and per-frame checkpoints with matching input,
configuration, implementation and runtime identities. Changed evidence stops resume.
With `--reuse-captures /absolute/path/to/original-captures`, a new output directory
receives independent copies after game, route, ordered patch, trace and every PNG
hash are checked. No engine is invoked in this mode; `--godot` remains a required
argument. Calibration is still frozen before measured cases are processed.

```sh
python3 -m agents.template_observations observe \
  --run /absolute/path/to/candidate-replay \
  --bank /tmp/expectrail-template-foreground/templates.json \
  --spec contracts/examples/test-spec-template.json --out /tmp/observations.json
```

`observe` exits 2 on disagreement or incomplete evidence. The benchmark also exits 2
when any configured accuracy, speed, false-alarm or seeded-detection target fails;
results survive target failure. Timing includes PNG decoding and matching, excludes
capture, bank preparation and checkpoint writes; all per-frame timings survive resume.

## Legacy compatibility and contracts

Existing `expectrail.template-ncc/v2` banks retain their recorded luminance matcher
and reproduce the original result. Explicit-frame `calibrate` still defaults to full
crops and floor 0.90. The earlier automatic crop-only profile retains its 10% inset
and 0.93 floor; it reached only 16.41% clean false alarms. Use the explicit foreground
options above for the new profile; the old profile is not the under-2% result.

Bank v1, measurement v1, the optional observations/v0 sensor extensions and the pose
catalogue ship with both writer and reader. Synthetic examples:
[bank](../contracts/examples/template-bank-foreground.json),
[observations](../contracts/examples/observations-template-foreground.json),
[measurement](../contracts/examples/template-measurement-foreground.json).
The v0 examples and schemas remain supported. Version mixing, altered bytes/masks,
missing confirmation and forged summary/region/seed claims are rejected.

Lighting, partial occlusion, palette collisions, unseen poses, rotation and nonuniform
scale can remain unsupported. Search is local; a distant object is not located. A
matched crop does not certify all sprite pixels, semantic identity, animation
correctness, arbitrary colour/text requirements or a different game. This remains
opt-in until separate validation supports broader use.
