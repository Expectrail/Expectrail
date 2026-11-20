# The Unity build runs on main only while Unity is deferred

## What changed

Sean decided on November 19, 2026 that the Unity build (`.github/workflows/unity.yml`) no longer runs on pull requests while Unity work is deferred until after the fund. Godot pull requests that touch the shared harness (`harness/unity/**`) were waiting on Sean's approval of the `unity` environment for every push. That held #639 for a day, and it was holding #559 and #570.

- On a pull request, the workflow still starts, but its `build` job is skipped, and `replay` and `cross-runner` follow it.
- On a push to main that touches the same paths, or when the workflow is dispatched, the build runs as before.
- Sean restricts the `unity` environment to main and drops its required reviewer, so only code already on main reaches the licence.
- A red Unity run on main is a red main. Under AGENTS.md, the merge guard reverts the merge that caused it.

## What was run

- The workflow file parses as YAML. The `pull_request` and `push` triggers carry the same four paths, and `build` has `if: github.event_name != 'pull_request'`.
- The full suite, in 3 parts: OK after `tests/test_unity_workflow.py` was updated to the new triggers (it asserted the old ones).

## Not done

- No Unity run on main has happened under the new trigger yet. The first merge that touches a Unity path is the first real run.
- Put the pull-request build back when Unity work resumes.

## Files

- `.github/workflows/unity.yml`
- `tests/test_unity_workflow.py`
- `docs/new-work/2026-11-19-unity-main-only.md`
