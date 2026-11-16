# Public seed measurements (#531, round two)

`scale.py` reuses the first-round route generator and observations. It reads the strict public
`bench/jit/public/defects.json` through `expectrail.repro.bench.load()`, then includes every
`bugs/reported/*.patch` not already listed there. It does not discover defects by walking other
bench folders. The current union is 24 defects and the upstream draw-order fix: 25 patches,
plus the clean game. Shared reported defects run once per seed, not twice.

The first measurement used seeds 0–199, 1,200 ticks each, with pinned Godot 4.7.2. Seeds
10000–10199 were reserved before that measurement, with no evaluation routes or traces inspected
while choosing the improvement. The artifact `preregistered-plan.json` records this split.

```sh
# Install/check the pinned binary. This is a public download, not a model call.
EXPECTRAIL_TOOLS="$PWD/work/pinned-tools" bash harness/get_godot.sh

# Clean first: this command starts no defect replay.
python3 -m tools.playtester.scale --out work/playtest-development \
  --start 0 --count 200 --ticks 1200 --jobs 4 \
  --godot "$PWD/work/pinned-tools/godot/Godot_v4.7.2-stable_linux.x86_64" --only clean

# Resume the exact same clean measurement, then run all public patches.
python3 -m tools.playtester.scale --out work/playtest-development \
  --start 0 --count 200 --ticks 1200 --jobs 4 \
  --godot "$PWD/work/pinned-tools/godot/Godot_v4.7.2-stable_linux.x86_64" --only all

python3 -m tools.playtester.analyze_scale work/playtest-development
```

The tool supplies writable XDG directories to its engine workers; it does not change HOME. It uses
four ordinary worker processes, not agents or model calls. Every replay starts the game afresh
through `harness.run.run(capture_frames=False)`. Routes, ticks and engine cadence are unchanged
from the first-round producer. Every build gets a separate import cache. Game patches are applied
only to copies; temporary-index commit objects identify the exact game blobs without moving HEAD
or changing the real Git index.

Each run retains:

- The seed route (shared across builds), complete report documents, and build/patch identities.
- A compressed raw engine trace, the harness replay record and engine log.
- A measurement containing trace hash, engine/isolation, observations, field hashes and all
  existing repro trace signals, plus failed-attempt records and elapsed time.

Successful records are resumable. A different base, seed range, tick count, producer source or
engine version is refused rather than mixed into an existing plan. Failed engine attempts may
retry up to three total attempts, and their logs remain. A missing or invalid replay is an error,
not a zero-report result. All clean seeds must complete before any defect replay starts.
Summarization requires the complete requested seed set by default. `--partial` is a progress
view, not a finished measurement or basis for a claimed miss rate.

## What the counts mean

Every clean-game report is counted as false, as requested. Counts include both total reports and
seeds with reports, broken down by observation. The first two examples per observation are retained
in the summary when they exist. A zero count has no examples; synthetic fixtures are not substituted.

A **candidate found** in the generated table means the defect produces an observation absent on
the clean game on that same seed. The same observation already present on the clean seed is not
counted as a new candidate, even at a different tick. This prevents moving an existing false alarm
from inflating discovery. It does not establish that the candidate describes the listed defect's
symptom. Incidental stops against obstacles must not be called infinite-jump findings. The final
results distinguish the candidate counts from the symptoms the reports actually describe.

## Why a miss was missed

The labels are those of `expectrail.repro.score.MISS_REASONS`, explained in
`expectrail/repro/breakdown.py` and the public bench README. This is not a new scorer or a
shared-verifier verdict:

| Existing label | Evidence used here |
| --- | --- |
| `wrong-predicate` | Current clean/defect replays differ on an existing repro signal, but the observations do not report the symptom |
| `no-signal` | Current traces differ on some recorded field, but no existing repro signal changes |
| `route-never-reaches` | Public counter/menu evidence plus the actual routes: no route opens the pause menu |
| `probe-language` | Public screen/draw evidence describes an effect these traces do not record; no new frame measurement is claimed |
| `undetermined` | The current traces/signals match and the available evidence cannot separate missing reach from missing observability |
| `flaky`, `budget` | Reserved for evidence of those conditions; no model budget or generated checks are used here |

Record fields are compared using their per-tick values, excluding `tick` and `frame`, as in
`repro.visibility`. Signals come from the existing normalizer and signal library, not new
bug-specific predicates. Any signal difference counts, however small: a changed incidental signal
does not prove the named behavior was reached. Older public screen/menu evidence is identified
in the basis and is never presented as a new capture of these seeded routes.

The tests use standard-library fixtures and explicitly block numpy and PIL imports. Engine runs
are separate, recorded measurements; no missing image package is silently treated as a successful
visual observation.

## The one observation change

After the complete initial breakdown, one optional observation was added: the player's recorded
body remains fully outside the game view for one physics second. The routes and the original
three observation functions are unchanged. This uses a spatial relationship a platformer player
would notice, rather than a known bug's mechanics, gravity, cooldown, or patch identity.

`offscreen.py` transforms all four corners of the logged collision body using the logged `view`
matrix. Partial visibility or touching an edge is not a finding. A visible or unknown sample
breaks the consecutive-tick window. A hidden player, absent position/body/view, non-finite value,
or degenerate transform is unknown. The duration is the trace's own physics tick rate: 120
consecutive samples in the bundled game. The report anchors the previous world position.

This is an engine prediction using collision geometry, not rendered-pixel proof. Intentional
transitions or artwork that differs from collision can confound it. Every report on the clean
game is still counted as false, without exemptions. The criterion is a suspicion for a report,
not an accept/reject decision.

The viewport must be independently measured in **the same coordinates as `trace.view`**.
A pinned-engine probe found the bundled game's headless logical viewport is **800×480**, with
origin (0,0) and identity final transform. Its dummy headless window is 64×64; that is not the
game view. The normal captured image is also a different coordinate system. Do not substitute
either size. The probe and output are included in the handover.

The original policy remains the standalone default (`producer.version=1.0.0`). `--viewport 800 480`
enables the additional observation (`producer.version=1.1.0`) while preserving issue #531's exact
report field shape. Neither report policy names checks or claims a cause.

## Fresh, paired evaluation

The observation and implementation hashes were frozen before generating any evaluation route.
Run these against a new output directory, keeping the independently verified dimensions:

```sh
python3 -m tools.playtester.scale --out work/playtest-evaluation \
  --start 10000 --count 200 --ticks 1200 --jobs 4 --viewport 800 480 \
  --godot "$PWD/work/pinned-tools/godot/Godot_v4.7.2-stable_linux.x86_64" --only clean
python3 -m tools.playtester.scale --out work/playtest-evaluation \
  --start 10000 --count 200 --ticks 1200 --jobs 4 --viewport 800 480 \
  --godot "$PWD/work/pinned-tools/godot/Godot_v4.7.2-stable_linux.x86_64" --only all
python3 -m tools.playtester.analyze_scale work/playtest-evaluation --policy original
python3 -m tools.playtester.analyze_scale work/playtest-evaluation --policy offscreen
python3 -m tools.playtester.audit_scale work/playtest-evaluation
```

Each fresh replay supplies **both policies**, so comparisons use the same seeds, routes and engine
trace. This requires 5,200 fresh engine replays, not two separate sets. Original reports remain
under `reports/`; combined-policy reports are under `reports-offscreen/`. Measurements explicitly
record both policies, and an absent policy is an error rather than a zero-report result. Analysis
writes `summary-original.json` and `summary-offscreen.json`. The auditor reads back raw traces,
reconstructs routes, recomputes fields/signals, regenerates both report policies and checks anchors
and exact field shape. It requires full local raw traces; the handover identifies its sampled
raw-trace subset separately from the complete per-seed records and report documents.
