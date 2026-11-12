# A SAM probe on frames from an outside game, for Sean to run (#263, #327, #330)

## What changed
Sean agreed on November 12 to a probe, not a verdict: can SAM find the player in a game it has
never seen, with a prompt nobody tuned? The answer feeds the tuning loop (#330). The difficulty is
that the model key and other people's code must never be in the same job.

- `tools/outside_trial.py --capture`: replays our routes on an outside project with the harness
  alone, the sandbox required, and keeps the frames and the trace. Nothing is judged.
- `.github/workflows/outside-sam-probe.yml`, started by a person only, two jobs:
  - `capture` has no secret. It fetches one project at its pinned commit, replays our route on it
    in the sandbox and uploads the frames and traces.
  - `probe` holds the key. It downloads those frames from the same run and runs
    `agents.sam_probe` on every Nth one with the prompt given. It never fetches, checks out or
    starts the outside project.
  - The run is started with a spend cap in dollars (at most 2) and stops at it.
- Tests hold each of those against the workflow file.

## What was run
- The capture on a project of our own (`tests/projects/event-input`, Godot 4.7.2, sandbox off
  because bubblewrap is not installed here): 70 frames, `trace.json`, `replay.json`. With the
  sandbox required, as the command line always asks, it refuses here: "a sandboxed replay was
  required and is not possible here".
- `python3 -m agents.sam_probe ... --dry-run` on that capture: "8 requests at most".
- `tests.test_outside_trial` on Python 3.12 and 3.13: 12 tests, OK.
- OBAAF check with the new workflow: 0 new.
- **The workflow itself has not run.** It holds a secret, so only Sean can merge and start it.
  **No call to SAM was made.**

## Not done
- The cap is only enforced once #343 is on main (`EXPECTRAIL_SAM_USD_CAP`). Do not start the probe
  before that: until then the variable is set and nothing reads it.
- The capture with the sandbox on has not run anywhere yet; its first run is the workflow's.
- The month's count across runs (#267). The workflow writes a "SAM budget" notice with its cap for
  that count to read later, and shares one concurrency group with future spending jobs.
- The probe looks for the player only. Ground, coins and enemies are not asked for.

## For Sean
At the default (every 10th of the first 120 frames, one prompt) a run is 13 images, about $0.03.
A sweep of 9 prompts is 117 images, about $0.29. Arithmetic at the list price, not a measurement.

## Files
`tools/outside_trial.py`, `.github/workflows/outside-sam-probe.yml`, `tests/test_outside_trial.py`
