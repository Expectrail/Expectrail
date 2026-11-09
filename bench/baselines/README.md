# Stability baselines

One file per machine type, named by its fingerprint id: `<id>.json`
(`expectrail.stability-baseline/v0`). Each file records what a route's replay hashes to on that
machine type, so a later run there can tell whether it still replays the same way.

- **Fingerprint.** The CPU model from `/proc/cpuinfo`, the CPU architecture, the Mesa version Godot
  printed in `godot.log`, and the engine version, renderer and device from `replay.json`. The id is
  the first 16 hex digits of the sha256 of those fields. A machine that differs in any of them gets
  its own file.
- **Hashes only.** Each entry is keyed by the sha256 of what was replayed: the route's sha256, the
  game tree, the patch sha256, the frame rate and whether frames were captured. It holds the frame
  count, the sha256 of the frame hash list, the trace's sha256, the number of replays and the date.
  No route name, frame or trace is stored.
- **Who writes them.** Only `python3 -m agents.stability ... --record-baseline`, and only when every
  replay was identical. An entry that already holds different hashes is never overwritten; remove it
  by hand if the change is expected. The overnight loop and the held-out bench read these files with
  `--stability` and never write them. Do not record held-out routes here: their hashes would be
  derived from the private set.
- **What a mismatch means.** If the replays agree with each other but not with this machine type's
  baseline, the route is flaky (needs-review), never a pass or a fail.

## Files

| File | Machine | Cases | Recorded |
| --- | --- | --- | --- |
| `ad62ebe3e044dcd8.json` | the 2-core cloud container this was built on, no GPU: Intel Xeon @ 2.10GHz, Mesa 25.2.8 llvmpipe (LLVM 20.1.2), Godot 4.7.2 | smoke route, clean game (stable pass); smoke route with `bugs/physics-fall-through/v1.patch` (stable fail) | Nov 9 |

This machine is not a GitHub Actions runner. A runner's CPU model can change from one job to the
next, so CI jobs will usually find no baseline for their fingerprint.

Record one:

```sh
python3 -m agents.stability --route harness/routes/smoke.json \
  --patch bugs/physics-fall-through/v1.patch --out runs/stability --record-baseline
```
