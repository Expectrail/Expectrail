# Remaining trial stops (issue text, not filed)

## Outside trial list cannot register a repository-root Godot project

What happened: `load_list` refused Breakout's `path: "."` with `TrialError: breakout: path must be a plain path inside its repository`. The pinned project's `project.godot` is at the root. The config-only CLI and harness now run it, but it remains outside the automated list.

Where to look: `tools/outside_trial.py`, `_PATH`, `load_list`, and sparse checkout/config overlay handling. Smallest safe direction: explicitly support the root sentinel while retaining traversal checks; add a root-project fixture and config overlay path. Do not relocate or vendor the game just to satisfy the list. [Probe output](trial-logs/21-registration-probe.log).

## Pointer auto-route explanation prints each tick instead of the sweep

What happened: the successful 407-tick auto-route prints hundreds of individual pointer moves. The Start click and useful movement result are difficult to find. [Output](trial-logs/08-auto-route.log).

Where to look: `expectrail/route.py`, `describe`. Summarize contiguous sweeps by start/end tick and coordinates while keeping the exact route as evidence. Preserve explicit button presses/releases and the movement/determinism results. This is a reporting issue, not evidence that the replay failed.
