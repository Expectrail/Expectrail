# Play seeds and ingest every report (#531)

From a checkout with Python 3, Git and the pinned Godot from `harness/get_godot.sh`:

```sh
python3 -m tools.playtester.command \
  --project /absolute/path/to/configured-project \
  --godot /absolute/path/to/Godot_v4.7.2-stable_linux.x86_64 \
  --start 10000 --count 200 --ticks 1200 --viewport 800 480 \
  --out /absolute/path/outside-project/playtest-command
```

The project needs `expectrail.project.json`, a Git HEAD, its routes and its own existing
approved contracts. This command does not create, approve or select a check. The benchmark
helper supplies a disposable config and copies the existing approved ground contract byte
for byte. It never modifies the bundled game.

Discovery uses the existing seeded routes and observations. An explicit viewport enables
the reach prerequisite's persistent offscreen observation; omit it to use the original three.
Every written report passes the merged `expectrail.orchestrator.playtest` writer and reader.
The lowercase semantic object `player` is the reader's and checkpoint's identifier.
Main's merged producer is unchanged. This command adapts its in-memory `Player` anchor to
`player`, appends `+ingest.1` to the producer version, and recomputes the canonical report ID
before the first report write. Its route, observation text and ticks are unchanged.

For every raw report the command runs a separate real subprocess:

```sh
python3 -m expectrail.cli ingest REPORT --project PROJECT --jobs-root JOBS --json --timeout 1800
```

No `--propose`, repair, engine substitution, model provider or in-process worker replacement
is used. The environment is restricted to local execution/rendering settings, with fresh XDG
directories and no inherited provider settings, credentials or paid API transport.
A display/Xvfb is needed for ingest's rendered replays. The regular product rule remains
`both`; missing visual evidence may produce **inconclusive**, which is reported separately
from **not-reproduced**. An engine suspicion is never counted as an approved reproduction.

`results.json` records every report's CLI exit code, job ID, actual reproduction reason,
approved check IDs, decision and whether the product's three precheck runs reached the anchor.
Failed jobs and unclassified results are explicit; the command exits nonzero for either.
Needs-review (CLI exit 2) is a valid completed intake, not a subprocess error.
`--ingest-jobs N` permits independent report jobs to run concurrently (default 1).
The job store, stdout, stderr, argv and product evidence remain under `intakes/`.
`--extra-report FILE` submits a hand-written report through the same path.

Grouping uses identical observation text, target build and anchor object, with pairwise
Euclidean distances no greater than either anchor's tolerance. IDs are sorted first; groups
are complete-link (a chain of individually close anchors cannot widen a group). Fault tick
is not a grouping condition. Every raw report is retained and ingested even when grouped.
The output lists all group members, raw counts, grouped counts and raw intake outcomes.

Rerunning the exact plan resumes completed seeds/intakes. Changed reports, changed source or
policy trees, altered plan parameters and partially written seed/intake folders are refused.
Inspect incomplete folders before retrying; they are never silently overwritten. The source
and policy digest is checked again before each intake. Output must be outside the project.

`--compact-replays` is an explicit storage option: after completed replay evaluation, hash and
remove rendered `frames/f*.png`, gzip traces, and remove discovery-only disposable replay
work copies. The result/status, report, replay manifest, trace, logs and removed-PNG manifest
remain. This does not alter capture settings or the policy. With this option the retained
job is evidence for the recorded outcome, not a complete offline image replay archive.

The entire public measurement (clean, public repro manifest, remaining reported patches,
then two false reports) is one local command:

```sh
python3 -m tools.playtester.command_bench \
  --out /absolute/path/public-command-measurement \
  --godot /absolute/path/to/Godot_v4.7.2-stable_linux.x86_64 \
  --start 10000 --count 200 --jobs 4
```

It creates committed disposable project copies and uses the same `batch` entry point.
It never walks a private or blind directory. `--only BUILD --count 1` is available for smoke
tests and is not the published 200-seed measurement. All reported results are diagnostic
local evidence, with the actual isolation mode recorded by the harness.

## This rebase

This command layer builds on main's merged reach implementation without modifying it.
Its plan fingerprints the producer, offscreen policy and command adapter. Results from the
older branch cannot silently resume under this adapter. The earlier 5,200-route / 322-report
measurement belongs to the original branch/base, not this rebase. It was not rerun on this
base. The new work log and handover record the actual rebased tests and smoke checks.
