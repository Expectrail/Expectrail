# A second Godot project through the one verify command (#251)

## What changed
- **`tests/projects/crate-run`**: a small Godot 4 project that shares no file with the bundled game.
  A crate (the node `Player`) walks and jumps on a flat floor of `TileMapLayer` tiles that
  `main.gd` builds in code, so the project holds no image. It has its own input actions, 60
  physics ticks a second where the bundled game has 120, one route (`routes/walk.json`) and one
  draft spec that nobody approved.
- **`tests/test_second_project.py`**:
  - With no game started (the gate tests' stand-in replay): the orchestrator's `godot` engine
    replays the game its arguments name, head and base; the gate's replay hands the harness that
    game and its checkout; no module on the verify path (`expectrail/gate/verify.py`, `record.py`,
    `expectrail/orchestrator/engines.py`, `request.py`, `runner.py`, `store.py`) names the bundled
    game; a project whose only spec is a draft is needs-review and nothing is replayed.
  - With `EXPECTRAIL_ENGINE_TESTS=required`, real Godot through `expectrail verify` (run as
    `python3 -m expectrail.cli verify`, the module the installed command starts): the bundled game is accepted; the second project
    is accepted and `findings.json` names its tree; the second project with its collision broken,
    compared with itself as it is, is rejected (pass before, fail after); the second project with
    only its draft spec is needs-review.
- **`.github/workflows/ci.yml`**: in the job `seeded-bugs`, one step runs those tests with the
  switch set and `EXPECTRAIL_SANDBOX: require`. In the job `package`, one step copies the second
  project out of the checkout and runs the installed `expectrail verify` on it; the step passes
  only on accept. No secret, no permission, no environment.
- **`docs/orchestrator.md`**: a section on verifying a second project and what such a project still
  has to match.
- No product code changed. The gate and the orchestrator already took the game from their
  arguments; what was missing was a second project and a run that shows it.

## What was run
- `EXPECTRAIL_ENGINE_TESTS=required python3 -m unittest tests.test_second_project -v`, on this
  machine with Godot 4.7.2 and Xvfb: 12 tests, OK, 41 s. The replays were not sandboxed: this
  machine has no bubblewrap.
- By hand before the test existed, `python3 -m expectrail.orchestrator verify` on the second project: `completed, accept`,
  `all 1 checks pass`, exit 0; on the broken copy against the clean one: `completed, reject`,
  `1 of 1 public checks fail after the change`, exit 1.
- `python3 -m unittest discover -s tests -t .` on the branch merged with main at a6bf26c:
  2,074 tests, 26 skipped, OK. Four of the skips are the real-Godot tests above, which the suite
  leaves out without the switch; the others are as on main here (no bubblewrap).
- `python3 -m tools.merge_guard --base origin/main --head HEAD`: `nothing to report`.
- The two new CI steps (the tests with the sandbox required; the installed command): not run when
  this was written.

## Not done
- **A spec approved for this project.** The tests judge it with the bundled approved spec
  (`agents/specs/player-stays-above-ground.json`), copied unchanged, as the gate tests and the
  sample already do. `tests/projects/crate-run/specs/crate-stays-above-floor.json` is a draft;
  approving it is Sean's step.
- **The installed `expectrail verify` on this machine.** #325 merged while this was being built, so
  the tests now go through `expectrail.cli`. The installed command itself is run only by the new
  step of the `package` job.
- **The shared verifier.** The `godot` engine is still the gate's `run_gate`; `observing` and
  `evaluating` are not separate phases, and the engine is still picked from `ENGINES` by adapter
  name, not from `harness/adapters.py`.
- **`harness.run.run` still falls back to the bundled game when no game is given.** The verify path
  always gives one (a test holds that). The older `agents/` callers rely on the fallback, so
  removing it is a wider change.
- **Sizes in code.** The position log draws the player's box at the bundled game's size; on the
  crate its bottom is 2.75 px above the crate's real bottom, inside the check's 20 px tolerance.
  The player must be the node `Player` and the ground must be tile collision. That is #259.
- **A reason that says a draft is waiting.** A project with only a draft spec gets "no checks ran";
  the record's `drafts` count is the only place that says why.
- A project nobody here wrote. That is #263.

## Files
`tests/projects/crate-run/` (`README.md`, `project/project.godot`, `project/main.tscn`,
`project/main.gd`, `project/player.gd`, `routes/walk.json`, `specs/crate-stays-above-floor.json`),
`tests/test_second_project.py`, `.github/workflows/ci.yml`, `docs/orchestrator.md`
