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

## Architect run (Linux, main 8083215e, Godot 4.7.2)
Applied cleanly (base two commits behind main). Full suite: OK, 31 skipped. Engine-gated tests with EXPECTRAIL_ENGINE_TESTS=required (body_box, event_input, ground_under, pause_input, second_project, auto_route_engine): OK. The three Run it samples are unchanged: accept, reject, accept. `harness.check_seeded`: every seeded bug still differs from clean, exit 0.

## Gate reads the base config

The gate was reading `captureFps` and the bindings from the head game, so the change under test
could set the yardstick. It now reads `expectrail.project.json` from the base checkout, as it reads
specs and routes, and passes that capture rate and those bindings to both arms, the held-out routes
and the repeat runs. The harness already takes the bindings as values; what changed is which file
is read. With no base, the local path still reads the game's own file. A head config that is added,
removed or changed is not an accept: it is counted in `checkProblems`, the same way as a spec or
route file the gate could not use, so the reader recomputes the decision and a failing check still
rejects. No new field was added to the findings record. A head file that is present and not valid
JSON is the same kind of difference: the gate still plays the base's config and writes a record,
and it names the read error. An invalid config on the base, or on the local path with no base,
still stops the run and names the field.

What was run: `python3` on PATH is 3.10.22 and has no tomllib, so the suite was CPython 3.12.15
(`/tmp/py312/bin/python -m unittest discover -s tests -t .`). Godot 4.7.2-stable is the binary
`harness/get_godot.sh` checked by SHA-512; it was not hidden or replaced. The three new tests with
`-v` were ok (`Ran 3 tests in 0.274s`, `OK`). On the base `80c8bb3c7959205d9314291e512946ccebf5d2c5`:
`Ran 3410 tests in 456.900s` / `OK (skipped=55)`. On this change: `Ran 3413 tests in 505.122s` /
`OK (skipped=55)`. Not run: nothing was pushed, and no pull request or GitHub comment was opened.
#260 was not started.


## Architect run (gate reads the base config)

Linux. The patch applied cleanly on `80c8bb3` as `af202e0`. Main (`191cc3d`, 48 commits ahead, #436 included) was then merged in as `76afcfa`, with one registry conflict in `setup.py`'s bundled modules, resolved by keeping this branch's `project_config` and main's `auto_fix` and `spend`. Godot 4.7.2 from `harness/get_godot.sh`, under `xvfb-run`.

- The three new tests in `tests.test_ci_gate.VerifyTest`, against `80c8bb3`'s `verify.py`, `harness/run.py` and `harness/adapters.py`: `FAILED (failures=2, errors=1)`. With the fix: `Ran 3 tests`, `OK`.
- `python -m harness.check_seeded --out runs/seeded-check`: exit 0 (not sandboxed here: no bubblewrap). CI's sinking step over those traces: `{'clean': 'pass', 'sinking_v1': 'fail', 'sinking_v2': 'pass'}`.
- `EXPECTRAIL_ENGINE_TESTS=required` on `tests.test_body_box`, `test_event_input`, `test_ground_under`, `test_pause_input`, `test_second_project`, `test_auto_route_engine`, `test_unknown_actions`: `Ran 80 tests`, `OK`.
- `python3 -m unittest discover -s tests -t .` on the merged result: `Ran 3587 tests`, `OK (skipped=31)`.

Not run: hosted CI (runs on push), the release gate suite. No model was called and nothing was spent.
