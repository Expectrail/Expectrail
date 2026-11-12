# Installing Expectrail

Expectrail is a Python package with one command, `expectrail`. This page says how to install it,
what the package holds, and what is not built yet. It is not on PyPI: publishing needs an account
and a token, which only a person sets up (#249).

## From a checkout

```bash
python3 -m pip install .          # in a clone; Python 3.12 or later
expectrail --version              # says "installed package" and where its files are
expectrail sample                 # three real verifications of the bundled game: accept, reject, accept
```

`expectrail sample` needs what any verification of a Godot project needs from the system: a
virtual display (`xvfb-run`), Mesa's software OpenGL, and `patch`, `curl` and `unzip`. Godot itself
is fetched on first use (4.7.2, checked against its SHA-512) and kept in the user's cache folder,
`~/.cache/expectrail` (or `$XDG_CACHE_HOME/expectrail`; `$EXPECTRAIL_TOOLS` names another place, and
`$EXPECTRAIL_GODOT` names an engine binary to use as it is). `expectrail doctor`, which will check
all of this and name the fix for each missing piece, is not built yet.

In a clone nothing changes: `python3 -m expectrail.orchestrator ...` and every other `python3 -m`
entry point work as before, and the engine stays in `tools/`.

## The command

| | |
| --- | --- |
| `expectrail verify`, `status`, `cancel`, `report` | Verification as a job ([orchestrator.md](orchestrator.md)). The same code, options and exit codes as `python3 -m expectrail.orchestrator`. |
| `expectrail sample` | Three real runs on the bundled game and a seeded bug. Exit 0 only when they decide accept, reject, accept. |
| `expectrail --version` | The version, whether this copy is a clone or an installed package, and where its files are. |
| `expectrail doctor`, `trust-check`, `repair` | Not built yet. Each says so, names its issue and exits 5. None prints a verdict. |

## What the package holds

The wheel holds what a verification runs, and nothing that could not work from an installed copy.

- **In it:** the gate and the orchestrator (`expectrail.gate`, `expectrail.orchestrator`) and the
  modules they import; four harness modules (`run`, `sandbox`, `tree` and the package's own); the
  reader of the engine's position log; the contract schemas; the bundled Godot game, the smoke
  route, one approved spec and one seeded bug, which are what `sample` runs.
- **Not in it:** the fixer, the fix loop and everything that reads a model key; the benches and the
  check generator (`expectrail.discovery`, `jit`, `repro`); every other seeded bug; anything
  held out. `tests/test_package.py` lists each part of `expectrail` that is left out, with why.
- **No dependencies.** A verification imports the standard library only. `jsonschema` is an extra
  (`pip install 'expectrail[contracts]'`) for checking documents against the schemas.

One top-level name is installed: `expectrail`. The harness is imported as `harness` and the log
reader as `agents.observations`, so the wheel carries them inside the package, under
`expectrail/_bundle`, laid out as the repository is, and `expectrail/__init__.py` puts that folder
first on the module path. `expectrail.resources.ROOT` is the one name for "where Expectrail's own
files are" in a clone and in an installed copy.

## Limits

- **`import harness` and `import agents` belong to Expectrail inside a process that has imported
  `expectrail`.** Another package that installs a top-level `harness` or `agents` (there is at least
  one widely used `agents`) is shadowed in that process. The `expectrail` command is its own
  process, so this matters only to a program that imports both. The real fix is to move the
  harness into the `expectrail` package; that touches nearly every file and is not done.
- Linux only as packaged. The macOS engine script is in the wheel and was not run from an installed copy.
- Not shown: Python below 3.12; an install from PyPI; the engine download itself from an installed
  copy with no cached file (CI hands the installed copy the download it already holds, and the
  copy's own script unpacks and checks it).
- No runner image and no release workflow yet (#249).
