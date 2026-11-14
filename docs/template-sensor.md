# Local template sensor (#262)

`agents.template_observations.TemplateObserver` is an **opt-in experimental observer**. It reads
pixels without a model, network request, or API key. It does not change any default observer,
acceptance rule, SAM adapter, or approved spec. This slice is available in a repository checkout;
it is not added to the verification wheel.

## What it measures

The sensor searches for a clean-build crop near the position predicted by the engine. For Godot,
the prediction is the player's own collision `body` box, transformed into captured-frame pixels
with the next tick's `view`, matching the harness's camera timing. All four corners are transformed.
The original fractional prediction is stored separately from the rounded pixel crop, so an
identical clean frame is not rescaled by rounding. No player size is copied from the bundled game's constants. The capture rate must divide the
recorded physics tick rate; gaps, duplicate ticks, and missing cameras are not filled in.

`expectrail.template-ncc/v2` uses NumPy normalized cross-correlation of luminance patches.
An integral image produces 16-by-16 area samples for batches of candidate locations. NumPy computes
correlations against templates grouped by scaled dimensions; every pixel position in the bounded
region is searched. There is no Python loop scoring individual locations. Ties use template order,
scale order, y, then x. Runtime NumPy/Pillow versions and BLAS thread environment settings are recorded by the benchmark. Coordinates are
`[left, top, right, bottom]`, half-open, origin at the top left, y down, in captured-frame pixels.
The box locates the calibrated rectangle; it is **not** a segmentation of the entire sprite.

Starting settings are similarity 0.90, agreement IoU 0.50, search margin 16 pixels, scales
0.75/1/1.25 relative to predicted size, one-pixel stride, 16-by-16 samples, and minimum luminance
standard deviation 8. A score is similarity, not a probability. Automatic calibration may raise
the 0.90 threshold, never lower it. It records failure to meet calibration targets explicitly.

Every observation document records those settings, algorithm version, coordinates, capture/physics
rates, the bank digest, clean-game/replay/trace digests, capabilities, and limitations. Each object
and frame records the prediction, searched region, raw match box and score, selected template frame
and scale, and the reason for its status:

- `matched`: above threshold and overlapping the engine prediction sufficiently.
- `not-found`: readable pixels were searched, but no template reached the threshold.
- `displaced`: matching pixels were found but did not agree with the engine prediction or supplied filter.
- `unavailable`: image, trace row, camera, or measured box was unavailable.
- `out-of-frame`: the predicted crop is not entirely on screen; partial matches are unsupported.

The raw match survives agreement filtering in the frame's `sensor` block. The observation's
`objects` list holds only matching, agreeing detections. The existing evaluator can read it, while
`summarize` and the measurement renderer report disagreement counts and reasons. An optional
`agreeing` callback has exactly the `{frame: {object: [detection]}}` input/output shape used by
`agents.unity_observations.agreeing`. It may remove detections, never add them.

`TemplateObserver.look(spec, run, keep=...)` and `describe()` implement the existing observer
interface. The adapter refuses to answer if any requested frame is unavailable/off screen, or
if no frame was measured. It never returns a partial positive observation as a complete answer.
A readable frame with no match is negative pixel evidence, distinct from an observer failure.
No new path is wired into the default verdict. Raw `from_replay`/CLI measurement documents can
contain unavailable rows for diagnosis; use `TemplateObserver.look` for judging, because it refuses
those incomplete documents. Do not interpret an unavailable row's empty detection list as a
measured absence.

## Clean calibration, not candidate learning

Use a separately trusted **clean** checkout containing the approved art. Pin its game-tree digest
from that checkout. `calibrate` requires the exact digest and a replay with no patch, verifies the
trace and each selected PNG against `replay.json`, and stores the cropped grayscale bytes and their
hashes in a standalone bank. An existing bank is never overwritten. Flat crops are refused.

A digest is provenance, **not an approval**: the operator is responsible for choosing the trusted
clean build and inspecting the selected crops. An unpatched candidate is not automatically clean.
No code here approves art or specs. The observation API only loads the frozen bank; it has no
candidate-calibration or learning path. Do not copy candidate pixels into a bank after seeing an
alarm. Animation poses and backgrounds absent from the clean bank may legitimately fail to match.

The benchmark's `calibrate_routes` path examines **every eligible captured training frame** from
three dedicated clean routes: walking/idle, jumping/double jumping, and firing, in both directions.
It selects distinct luminance appearances automatically (feature correlation below 0.985) and adds
a horizontal mirror of each selected crop. Selection is deterministic in route/frame order. The
record includes selected frames, source replay digests, mirroring flags and the selection setting.
More than 2,048 selected templates is an explicit error, not silent truncation.

A fourth clean route, with separate timing and seed, validates the frozen selection. Threshold
selection uses player-region positives and displaced off-player negatives from **this calibration
route only**. It chooses the first threshold from 0.90 through 1.00 in 0.01 steps that gives at least
95% positive matches and at most 1% negative matches. If none does, it retains 0.90 and records
`calibration.status: unmet` and both counts. That is not a successful calibration. Training and
validation frames are excluded from measured rates; neither measured clean nor bug frames can
select a crop or change a threshold. Clean routes are public and exercise the same actions as the
measured routes; this is not evidence of generalization to other games or all animation states.

```sh
python3 -m pip install -r requirements-dev.txt
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m agents.template_sensor_bench \
  --godot /absolute/path/to/Godot --out /tmp/expectrail-template-measurement-v2
# Resume the same v2 evidence directory after an interruption:
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m agents.template_sensor_bench \
  --godot /absolute/path/to/Godot --out /tmp/expectrail-template-measurement-v2 --resume
```

The explicit-frame `agents.template_observations calibrate` command remains available for controlled
fixtures; it does not perform the automatic bank/threshold calibration described above. Use the
benchmark path for the reported animation coverage. Its bank can subsequently be consumed with:

```sh
python3 -m agents.template_observations observe \
  --run /absolute/path/to/candidate-replay \
  --bank /tmp/expectrail-template-measurement-v2/templates.json \
  --spec contracts/examples/test-spec-template.json --out /absolute/path/to/template-observations.json
```

The standalone `observe` command exits 2 on a disagreement or missing evidence. This is an advisory
measurement command, not a product verdict. Pixel processing uses the standard library, Pillow and
NumPy. Both imaging dependencies are pinned in `requirements-dev.txt`; the default verifier has no
new runtime dependency.

For explicit integration in a caller that has chosen this observer:

```python
from agents.template_observations import TemplateObserver
observer = TemplateObserver("templates.json", required_capabilities=("presence", "position"))
observations = observer.look(spec, run)  # NoAnswer on incomplete/unsupported evidence
```

Godot's built-in prediction covers `player` only. Additional named sprites can use an explicitly
supplied `predicted={frame: {name: box}}` map during calibration and observation. Every requested
object must have a clean template; missing objects, including ground, are never replaced by
engine-only detections. Natural-language prompts label the object binding, not a semantic judgment.

## What it cannot certify

Colour is discarded. Uniform brightness/contrast changes are normalized away, and sample resizing
loses fine details. It cannot certify text, semantic identity, animation correctness, full sprite
boundaries, rotations, nonuniform scaling, partial occlusion, or objects outside its search region.
Similar art or background can match; an engine collision box does not prove a sprite is visible.

Callers must declare any additional required distinction through `required_capabilities`.
`colour`, `text`, or `identity` requirements raise `NoAnswer`; unsupported assertion types also
raise it. The current spatial assertion types are supported, but their object prompts are not
proof that a colour or semantic requirement was checked. Do not use this observer to certify one.

## Measurements and resume

See [the recorded Linux report](template-sensor-measurement.md) and its
[JSON evidence](template-sensor-measurement.json) for this revision's rates and timing. The contract
examples and unit-test images are synthetic and are not included in those real-game counts.
The previous revision's Linux results supplied by Sean were 53/120 clean-smoke and 32/90
clean-combat matches, about 3 seconds per frame; its benchmark was stopped before bug cases.

The benchmark needs an existing local Godot binary and display/rendering dependencies. Nothing is
downloaded. It uses the harness to copy the bundled clean game and applies public patches to
copies; source game files stay untouched. Four calibration captures precede any measured replay.
Then it runs clean smoke, combat and traversal, followed by invisible-player, sinking and
fall-through cases. The invisible-player case applies the existing fall-through patch followed by
`agents/fixtures/fix-but-hide-player.patch`, which repairs collision but draws the player behind
scenery. Some frames can remain visible; the report gives actual counts.

`progress.json` records completed captures, exact inputs, runtime versions, frozen bank digest and
completed cases. Each measured run saves `sensor-progress.json` **after each frame**, with the
observation and its elapsed sensor time. Completed observations and per-run results are saved
before starting the next run. Writes use temporary files and atomic replacement. Progress is also
printed after captures, bank freezing, every 30 measured frames and each completed case.

`--resume` verifies capture metadata, trace/PNG hashes, bank digest and checkpoint identities before
reusing them. It resumes remaining frames without recalibration or recomputing completed frames.
Changed inputs, pixels, bank, settings or runtime versions are refused. An interrupted calibration
selection is recomputed from the saved clean captures; an interrupted engine capture may need to
be repeated. The old v1 manifest/algorithm cannot resume into v2: start a new output directory.
The progress files are local resumable evidence, not signed attestations against malicious editing.

Agreement = matched / measured object-frames. Clean false alarms = (not-found + displaced) /
measured object-frames. Unavailable and off-screen predictions are reported separately and excluded
from these two rates; no measured frames means a null rate. The **95% target**, however, uses all
requested frames on each clean measured route, including unavailable/off-screen frames. It must
hold on every clean route. Legitimate clean occlusion counts as a false alarm. The engine's
visibility flags are never used as positive pixel evidence.

The published timing uses one OpenBLAS/OpenMP thread, as in the commands above. More BLAS threads
can make these small matrix multiplications slower; the observer does not change its caller’s
thread settings. Timing includes PNG decoding, matching and frame-record construction, excluding Godot capture,
bank preparation and checkpoint writes. Mean, p95 and maximum are reported for every run; original
per-frame times survive resume. The speed target is conservatively assessed as **every measured
frame below 0.3 seconds**, not just the mean. Rendering and calibration still contribute to total
wall time. The command exits 2 if either target is missed, clean evidence is empty, or no
invisible-player alarm is demonstrated. It retains all results on target failure.

Do not tune the bank or threshold after reading measured or bug results. A matching crop does not
prove all sprite pixels are correct. An invisible-player alarm is pixel evidence of disagreement,
not proof that every hidden frame was detected. No default verdict uses this sensor.

## Contracts

The optional `model.sensor` and per-frame `sensor` blocks extend observations/v0 while preserving
existing box/score consumers. The [observation example](../contracts/examples/observations-template.json),
[bank example](../contracts/examples/template-bank.json), and
[measurement example](../contracts/examples/template-measurement.json) are synthetic. The new bank
and measurement schemas ship with their writers and readers. The measurement reader verifies rates
against counts before rendering them; no claim rests on an unexplained percentage.
