# Installing Expectrail

Expectrail is a Python package with one command, `expectrail`. This page says how to install it,
what the package holds, and what is not built yet. It is not on PyPI: publishing needs an account
and a token, which only a person sets up (#249).

## From a checkout

```bash
python3 -m pip install .          # in a clone; Python 3.12 or later
expectrail --version              # says "installed package" and where its files are
expectrail doctor                 # does this machine have what a verification needs? names the fix for what is missing
expectrail sample                 # three real verifications of the bundled game: accept, reject, accept
```

`expectrail sample` needs what any verification of a Godot project needs from the system: a
virtual display (`xvfb-run`), Mesa's software OpenGL, and `patch`, `curl` and `unzip`. Godot itself
is fetched on first use (4.7.2, checked against its SHA-512) and kept in the user's cache folder,
`~/.cache/expectrail` (or `$XDG_CACHE_HOME/expectrail`; `$EXPECTRAIL_TOOLS` names another place, and
`$EXPECTRAIL_GODOT` names an engine binary to use as it is). `expectrail doctor` checks all of this
and names the fix for each missing piece.

## `expectrail doctor`

```bash
expectrail doctor                 # exit 0: nothing required is missing; exit 3: something is
expectrail doctor --json          # one expectrail.doctor/v1 document (contracts/doctor.v1.schema.json)
expectrail doctor --isolated      # also require the replay sandbox, as the isolated class does
expectrail doctor --no-fetch      # only look for the engine; do not download it
```

It checks the machine and is not a verdict on any change. Each piece is checked the way a run uses it:

| Piece | How it is checked | Required |
| --- | --- | --- |
| Python | 3.12 or later | yes |
| Godot | found as a replay finds it (so the first `doctor` fetches it, SHA-512 checked), and `--version` says 4.7.2 | yes |
| A virtual display | `xvfb-run` is on the PATH (Linux; not checked elsewhere) | yes |
| OpenGL | the engine draws one frame of an empty project, started as a replay starts it, and names its device. A device other than Mesa's `llvmpipe` passes with a note: every recorded run used `llvmpipe` | yes |
| Free disk | 1 GB in the engine's folder and the temporary folder (the engine is 140 MB; one replay's 120 frames were 24 MB) | yes |
| The replay sandbox | bubblewrap, by the probe a replay uses | only with `--isolated` |
| `patch` | on the PATH: `sample` and seeded bugs put a patch on a copy of the game | yes |
| `curl`, `unzip` | on the PATH: they fetch the engine | no; when the engine cannot be fetched, the engine's own line names them |
| A vision key | present or absent in the environment (`MODEL_API_KEY`, `EXPECTRAIL_GLIMMER_API_KEY`, `FIREWORKS_API_KEY`, `EXPECTRAIL_VLM_API_KEY`). Only "is it empty" is looked at; the value is never printed. A `.env` file is not read | no |

**Without a vision key.** Today `expectrail verify` and `sample` judge on the engine's record only and
use no key, so the key changes nothing yet. Under the two-observer rule (#327) a run without a key
still rejects a failing change and accepts nothing: an accept needs the visual observer's evidence.
`doctor` says this on its last check.

**`doctor` and a run cannot disagree about a tool.** The engine's preflight
(`GodotGate._tools`) asks `expectrail.doctor.for_run()`, the part of the same list every run needs
(Godot, the display, OpenGL, disk), checked by the same functions. So when `doctor` passes, a job is
not stopped for a missing tool, and when a job is stopped its `TOOL_MISSING` diagnostic carries the
same words and the same fix. `doctor` asks for more than the preflight (`patch`, Python), never less.
This makes the preflight stricter than it was: it used to look only for the engine's file and
`xvfb-run`, and now also asks the engine its version and has it draw a frame (0.7 s on one machine).

In a clone nothing changes: `python3 -m expectrail.orchestrator ...` and every other `python3 -m`
entry point work as before, and the engine stays in `tools/`.

## The command

| | |
| --- | --- |
| `expectrail verify`, `status`, `cancel`, `report` | Verification as a job ([orchestrator.md](orchestrator.md)). The same code, options and exit codes as `python3 -m expectrail.orchestrator`. |
| `expectrail sample` | Three real runs on the bundled game and a seeded bug. Exit 0 only when they decide accept, reject, accept. |
| `expectrail --version` | The version, whether this copy is a clone or an installed package, and where its files are. |
| `expectrail doctor` | Checks the machine (above). Exit 0 or 3. Not a verdict. |
| `expectrail trust-check`, `repair` | Not built yet. Each says so, names its issue and exits 5. None prints a verdict. |

A command line that cannot be read (a missing or unknown option, on any command) exits 5, with the
usage on stderr and "Nothing was run". It was 2 until November 12, 2026, which is also needs-review.

## What the package holds

The wheel holds what a verification runs, and nothing that could not work from an installed copy.

- **In it:** the gate and the orchestrator (`expectrail.gate`, `expectrail.orchestrator`) and the
  modules they import; five harness modules (`run`, `sandbox`, `tree`, `adapters` and the package's own); the
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

## A release

`.github/workflows/release.yml` builds the wheel for a version tag and attaches it to the run:

- A tag `v<version>` builds from that commit, and only when it is the package's own version
  (`expectrail/__init__.py`); any other tag builds nothing and says why. A dispatch builds from main
  only, to try the workflow.
- The wheel is installed into a clean venv and its command must say "installed package" and the
  version. The wheel and its SHA-256 go up as the run's artifact `expectrail-<version>-wheel`, kept 90 days.
- It reads only and holds no secret. It publishes nowhere: PyPI or a container registry needs an
  account and a token, and pushing the tag is a person's step too.

It has not run yet: no tag has been pushed and it has not been dispatched.
`tests/test_release_workflow.py` runs its version step in bash and checks its shape.

## Limits

- **`import harness` and `import agents` belong to Expectrail inside a process that has imported
  `expectrail`.** Another package that installs a top-level `harness` or `agents` (there is at least
  one widely used `agents`) is shadowed in that process. The `expectrail` command is its own
  process, so this matters only to a program that imports both. The real fix is to move the
  harness into the `expectrail` package; that touches nearly every file and is not done.
- Linux only as packaged. The macOS engine script is in the wheel and was not run from an installed copy.
- Not shown: Python below 3.12; an install from PyPI. The engine download itself from an installed
  copy with no cached file was run once by hand (`expectrail doctor` with an empty home, November 12,
  2026, 5.6 s); CI does not do it: it hands the installed copy the download it already holds, and
  the copy's own script unpacks and checks it.
- `doctor` was not run in a clean container, on macOS, or on a machine with another OpenGL device.
- No runner image yet. The release workflow has not run (see below).
