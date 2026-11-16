# Expectrail playtester (#531, producer)

This tool plays seeded random inputs from the game's start through the existing Godot harness.
It reads engine traces, spends nothing on models, and writes one `expectrail.playtest-report/v1`
document per observed symptom. It does not ingest reports, generate checks, approve anything,
invoke a fixer, or decide whether a change is acceptable.

```sh
python3 -m tools.playtester --project game/platformer \
  --commit "$(git rev-parse HEAD)" --seed 0 --ticks 1200 --out work/playtest-0
```

`--commit` must name the exact project bytes played; the standalone producer takes this identity
from its caller. The bundled-game experiment below verifies every game blob against its local
target commit, including checking for extra files. Output must not already exist. Optional
`--godot /absolute/path/to/godot` selects an installed binary; otherwise the harness uses its
normal pinned binary. A failed replay or incomplete trace is an error, never a zero-report result.

The input-map reader is `expectrail.route.input_map` (#329), including project-config precedence.
The route uses the mapped `move_left` and `move_right` actions when available, otherwise recognised
movement actions. Mapped `jump` and `shoot` receive short random taps. Player-two aliases and menu
actions are excluded in the bundled game: they share keys or switch away from single-player play.
One randomly chosen movement action or idle interval lasts 45–210 ticks, separated by 0–20 ticks;
taps last 1–8 ticks, spaced 12–45 ticks apart. A local Python `random.Random(seed)` and sorted map
make generation repeatable. Seeds are unsigned 32-bit integers; routes are 1–1,800 ticks (default
1,200, ten seconds at the bundled game's 120 Hz). Inputs never schedule a snapshot or teleport.

The deliberately small anomaly set is:

| Observation | Recorded condition | Limit |
| --- | --- | --- |
| Falls below the level | Player origin exceeds the largest y in `levelSurfaces` by more than 64 px | Requires tile geometry; an intentional pit can produce this observation |
| Stops while moving | One movement action held continuously for 120 ticks; every sampled position within 0.5 px of the first | A wall, menu, or intended obstacle can look the same |
| Keeps turning | Facing alternates on eight consecutive steps after establishing one horizontal direction; each step moves at least 0.25 px in that direction | Cannot see other visual or animation problems |

The producer emits only the first occurrence of each symptom on a route. Missing player samples
break windows; missing geometry disables only the below-level observation. No score/counter is
invented: the current harness does not record a numeric score. The report's bug text describes
what happened to the player; it names no check and claims no cause. `preFaultTick = faultTick - 1`;
the anchor is that previous row's bound `Player` world position, with 2 px tolerance. The whole
route remains in the report. IDs hash the canonical report payload, including target commit and
producer version. Same route, target and trace produce byte-identical reports; engine determinism
is measured separately, not guaranteed for arbitrary games or across engine versions.

Each run retains `route.json`, `summary.json`, the harness's `trace.json`, `replay.json` and
`godot.log`, and `reports/*.json` when there are findings. Harness copies contain the game;
the original game is never modified.

## Repeat the public experiment

From a clean checkout of the recorded base plus this patch:

```sh
python3 -m unittest tests.test_playtester -v
mkdir -p work/runtime/data work/runtime/cache work/runtime/config
XDG_DATA_HOME="$PWD/work/runtime/data" \
XDG_CACHE_HOME="$PWD/work/runtime/cache" \
XDG_CONFIG_HOME="$PWD/work/runtime/config" \
python3 -m tools.playtester.bench --out work/playtest-measurement \
  --seeds 4 --ticks 1200 --godot /usr/local/bin/godot
```

Use the architect's installed binary path, or omit `--godot` for the harness default. The XDG
directories are needed when the sandbox cannot write Godot user data under the home directory.
They do not change the home directory. The recorded run used Godot 4.6.3; the repository pins
4.7.2, so this result makes no claim about that version.

The experiment applies each `bugs/reported/*.patch` to its own copy. It creates deterministic
local Git commit objects using a temporary index, based on HEAD with just that game patch.
These commits identify the build in each report; they do not move any branch or touch the real
index. Their author/committer is Expectrail at an invalid example address, with a fixed date.
`builds.json` records base/patch identities. Re-running `build_commit(base, patch)` reconstructs
the same commit on the architect's checkout. No commit or artifact is pushed.

Every actual producer report and two hand-written false reports are replayed three fresh times
on their own unchanged target build. The experiment measures the producer's same worded symptom
at `faultTick`, independently of the `Player` anchor at `preFaultTick`. Anchor reach is Euclidean
world distance `<= tolerancePx`. An anchor miss takes precedence over non-reproduction. A symptom
at a different tick does not reproduce the stated report. It also records whether the three full
traces are identical. The false idle report claims a fall on an idle clean route. The false-anchor
report copies the first producer report and moves its anchor x by 10,000 px (or copies the idle
report if the producer has no findings).

`filter.json` and `experiment.json` contain counts, per-attempt booleans and results. All report
documents, routes, raw traces and engine logs are retained. This is an engine-only measurement
of these observations, **not a run of the ingest command or of shared-verifier checks**. The
result strings describe what that filter would exclude before a fixer; they are not gate verdicts.
The ingest/contract builder owns the integration and arbitrary-report semantics.

Recorded counts and limitations: [docs/playtester-results.md](../../docs/playtester-results.md).
