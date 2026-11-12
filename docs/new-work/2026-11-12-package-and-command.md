# A package and the `expectrail` command: the wheel installs, and the real sample runs from the installed copy (#249, first part)

## What changed

There was no `pyproject.toml` and no command: everything was `python3 -m ...` from a clone.

- `pyproject.toml` and a small `setup.py`: `pip install .` builds a wheel with one top-level name,
  `expectrail`, no dependencies, and the `expectrail` command.
- The wheel holds what a verification runs and nothing that could not work installed: the gate, the
  orchestrator and what they import, four harness modules, the position-log reader, the schemas,
  and the bundled game, route, spec and seeded bug that `sample` runs. The fixer, the loop, the
  benches and the check generator are not in it.
- The harness and the game sit beside the package in the repository. In the wheel they are inside
  it, under `expectrail/_bundle`, laid out as the repository is. `expectrail/resources.py` is the
  one place that says where Expectrail's own files are; seven modules that each worked it out from
  their own path now ask it. `expectrail/gate/record.py` applies the same rule itself: it is the
  trusted comment job's code and imports nothing of ours (a test holds the two to one answer).
- `expectrail/cli.py`: `verify`, `status`, `cancel`, `report` and `sample` are the orchestrator's
  commands, called, not reimplemented, with the same exit codes. `doctor`, `trust-check` and
  `repair` say they are not built, name their issue and exit 5.
- `harness.run.tools_dir`: one rule for where the engine download and the import cache live. A
  clone keeps `tools/`; an installed copy uses the user's cache folder, because the place a package
  is installed is not one to write into. `harness/get_godot.sh` takes the folder from
  `$EXPECTRAIL_TOOLS`, and is run with bash by name.
- CI job `package` (Python 3.12): builds the wheel, installs it with pip into a new environment,
  leaves the checkout and runs the real sample from the installed copy.

## What was run

- `python3 -m unittest discover -s tests -t .`: 2,043 tests, OK, 22 skipped (bubblewrap and Unity, as on main).
- `tests/test_package.py`, 15 tests. It builds the wheel and reads it: one top-level name; every
  part of `expectrail` is in it or listed as left out with a reason; every `import` of `expectrail`,
  `harness` or `agents` in a packaged module names a module the wheel holds (one stated exception,
  the SAM observer, which no verification asks for); the bundled game is the repository's, file for
  file, by digest. Then, from the wheel unpacked into a new virtual environment with no other
  package, in another folder with the environment cleared: it finds its files inside itself, runs
  its own harness, keeps its tools under the home folder, and a real job with a real worker gives
  needs-review, exit 2, for a checkout with no game.
- Real Godot 4.7.2, the same unpacked wheel, environment cleared, outside the checkout:
  `expectrail sample` exit 0; accept, reject, accept, each as expected. The engine was named with
  `$EXPECTRAIL_GODOT` (this machine cannot download), and no `jsonschema` was importable.
- Not run here: `pip install` of the wheel (this machine has no network for pip; the wheel was
  unpacked, which is what an install of a pure wheel does, less the script). The `package` job
  does the real install and is the proof; its run is linked on the pull request.
- The OBAAF check: 0 new findings. `tools.merge_guard`: see the pull request.

## Not done

- `expectrail doctor`, the runner image, the release workflow, and the README leading with the
  install line: the rest of #249, in their own pull requests.
- Moving the harness into the `expectrail` package. Until then an installed copy puts its
  `_bundle` folder first on the module path, and shadows any other top-level `harness` or `agents`
  in a process that imports `expectrail` (docs/install.md, Limits).
- Python below 3.12, macOS from an installed copy, and the engine download with no cached file from
  an installed copy: not shown.
- The `package` job is not a required check. Adding it to the ruleset is a repository setting.

## Files

- `pyproject.toml`, `setup.py`, `requirements-build.txt`, `.gitignore` (new or changed at the root)
- `expectrail/resources.py`, `expectrail/cli.py` (new); `expectrail/__init__.py`, `expectrail/contracts.py`,
  `expectrail/timing.py`, `expectrail/gate/record.py`, `expectrail/gate/verify.py`,
  `expectrail/orchestrator/cli.py`, `request.py`, `runner.py`, `sample.py`, `store.py`
- `harness/run.py`, `harness/get_godot.sh`
- `tests/test_package.py` (new)
- `.github/workflows/ci.yml` (the `package` job)
- `docs/install.md` (new)
