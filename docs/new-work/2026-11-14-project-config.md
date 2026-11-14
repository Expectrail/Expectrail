# Project config: bindings, rates and actions, no sizes (#259)

## What changed

A game may carry `expectrail.project.json` next to its project file. The format is
`expectrail.project/v1` (schema, example, and `expectrail.project_config`, which uses the standard
library only). It names the adapter, the entry scene, the viewport, the physics tick rate, the
capture rate, the input actions, and one binding per object. A binding is a role mapped to a node
path or a group, and the texture that object is drawn with. It does not name sizes. A provider
value is a `ref:` or `env:` name, never a secret. Unknown fields, a path that leaves the project,
and two roles that name the same node or group are refused.

No file means the game has no config. The bundled game has none, and the verify path keeps the
rates and the node names it had. A file that is present and not valid stops the run and names the
field. The route reader, the gate and the harness all do this. None of them treats a bad file as
a missing one.

Python reads the file and passes the bindings to the Godot harness as `--bindings=<json>`. A path
on this machine is not passed: inside the sandbox the game is a copy, and a host path would not be
there. The copy still contains the config, because the whole project is what is copied.

`agents/observations.py` draws the player's box from the row's `body` when that box is there, and
from the bundled constants only when it is not. Coins stay on their constant. The ground check
still uses its feet constant.

`tests/projects/crate-run` has the first config: the player node `Player`, the texture
`res://crate.svg`, and 60 ticks a second. The verify path takes that capture rate when the caller
does not pass one (`fps=None`). Two tests that record the harness call were updated for that
argument. They still require the sandbox mode and the game they were given.

## What was run

Base `6e6ca6a8a85f7518cc890116bdcfd02d2c9d010c` (origin/main, 2026-11-13 23:39 -0500).

`/tmp/py312/bin/python -m unittest discover -s tests -t .` (CPython 3.12.15) in this container:
`Ran 3250 tests in 371.162s`, `OK (skipped=59)`. The command was not `-v`, so the skip reasons
were not printed.

Godot 4.7.2 is in `tools/godot`. This container was missing `libXcursor` and `libwayland-client`;
those two libraries were unpacked where the loader finds them, and the engine then started. The
tests that replay when that binary is present ran as part of the 3250. The tests gated on
`EXPECTRAIL_ENGINE_TESTS=required` were not required. No model was called and nothing was spent.

## Not done

- The bundled game has no `expectrail.project.json`. It keeps working without one. Giving it a
  config that reproduces today's results is still open.
- The ground check still takes the feet from `FEET_OFFSET`, not from `body`. Coins are still a
  constant 10.4 px. The harness does not yet log a screen box, a visibility and a role for every
  bound object the way the Unity recorder does.
- Crate Run's player node is still named `Player`. A second project whose player is not that name
  was not added.
- Unity is named by the schema and is not read by the Unity harness.
- The real engine was not run on the maintainer's Linux machine. The 59 skips were not listed.

## Files

- `contracts/project.v1.schema.json`
- `contracts/examples/project.json`
- `docs/project-config.md`
- `docs/contracts.md`
- `docs/harness.md`
- `docs/new-work/2026-11-14-project-config.md`
- `expectrail/project_config.py`
- `expectrail/contracts.py`
- `expectrail/route.py`
- `expectrail/gate/verify.py`
- `agents/observations.py`
- `harness/run.py`
- `harness/adapters.py`
- `harness/godot/expectrail_harness.gd`
- `setup.py`
- `tests/test_project_config.py`
- `tests/test_schema_pattern.py`
- `tests/test_ci_gate.py`
- `tests/test_engine_from_adapter.py`
- `tests/projects/crate-run/project/expectrail.project.json`
- `tests/projects/crate-run/project/crate.svg`
- `tests/projects/crate-run/README.md`
