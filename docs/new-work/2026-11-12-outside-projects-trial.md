# The outside projects trial: a pinned list, a script and a workflow (#263)

## What changed
Until now Expectrail had only ever verified the bundled game and projects written for its tests.
Sean agreed on November 12 to a CI job that runs it on projects the team did not write.

- `tests/outside/projects.json`: two projects from `godotengine/godot-demo-projects`, each pinned to
  a full commit, with our own route for each under `tests/outside/`. Nothing of a project is copied
  into this repository.
- `tools/outside_trial.py`: fetches a project at its commit (only its folder), lays out a checkout
  (the project, our routes, the bundled approved spec copied unchanged), runs `expectrail verify`
  on it, and writes what happened: exit code, verdict, reasons, seconds, checks.
- `.github/workflows/outside-trial.yml`: runs it on pull requests that touch the trial or the
  in-game harness, and on request. No secret, a read-only token, the replay sandbox required for
  every replay. A needs-review or a reject is a finding, not a failure of the job.
- `docs/outside-projects.md`: the page that will hold the results, with run links only.

## What was run
- `python3 -m unittest tests.test_outside_trial` on Python 3.12 and 3.13: 6 tests, OK. They fetch
  and start nothing from outside: the list's rules, the checkout's layout on a stand-in folder, the
  recording of a verdict and of a code that is no verdict from a stand-in command, and that the
  workflow holds no secret and requires the sandbox.
- OBAAF check with the new workflow: 0 new.
- **No outside project was started by me.** My session refused to run code from outside. The first
  run is this pull request's own `outside-trial` job; its result is added to
  `docs/outside-projects.md` from the run, not from expectation.

## Not done
- The results. See above.
- A project from outside the Godot organisation.
- A check that fits a top-down game (#329, #330), and names and sizes out of code (#259).
- The routes were written from reading the projects' input maps, not from playing them.

## Files
`tests/outside/projects.json`, `tests/outside/kinematic-character/routes/walk.json`,
`tests/outside/dodge-the-creeps/routes/dodge.json`, `tools/outside_trial.py`,
`.github/workflows/outside-trial.yml`, `tests/test_outside_trial.py`, `docs/outside-projects.md`
