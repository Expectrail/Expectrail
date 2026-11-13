# The verify path takes its engine from the adapter registry (#251)

## What changed

The gate and the orchestrator's `godot` engine named Godot themselves: the replay called
`harness.run.run`, a project folder was "one that holds `project.godot`", the game's digest left out
Godot's folders, a spec's window was counted at 60 frames a second, and the engines were a table
written by hand. All of that now comes from the engine's entry in `harness/adapters.py`.

- An adapter says whether the verify path can run on it. Four new fields, each with a default that
  means "no verify path": `verify_run` (the replay a verification makes; it takes the game, the
  sandbox mode and the checkout a link may lead into, and has no default game), `project_file`,
  `title` and `missing` (what a run needs and this machine lacks). `godot` has all four; `web` and
  `unity` have none. `adapters.verifying()` lists the adapters that have a verify path.
- `run_gate(adapter="godot")` asks the adapter for the replay, the project file, the folders left
  out of the digest and the capture rate. A name the registry does not hold, or an adapter with no
  verify path, is a `ConfigError` before anything is replayed. With no capture rate the gate cannot
  count a spec's window, and under the rule `both` nothing then passes.
- `expectrail/orchestrator/engines.py`: `ENGINES` is no longer a table. It has one engine for every
  registered adapter that has a verify path, read from the registry at each lookup. `Gate` is the
  gate's verification on any such adapter; `GodotGate` is `Gate` on `godot`, with the same
  arguments as before. The preflight's tool list is the adapter's `missing`, which for Godot is
  `expectrail doctor`'s list, as before.
- A job that names an adapter with no verify path completes as needs-review with `INPUT_INVALID` and
  says which adapters have one. Before, `web` and `unity` got "no adapter named 'unity'", which was
  not true: they are registered.
- A job's trees (`expectrail/orchestrator/request.py`) are taken with the folders of the adapter the
  request names, the same list the gate uses, so the worker's check that the evidence is about the
  job's tree holds for any engine. An adapter the registry does not hold leaves nothing out.
- `contracts/findings.schema.json`: `adapter` was `enum: ["godot"]` and is now the adapter-name
  pattern the verify request already uses. The writer (`run_gate`) writes the adapter's name; the
  reader (`rec.check_record`, the review page) takes any name of that form. The three examples say
  `godot` and are unchanged.

- The wheel carries `harness/adapters.py` (five harness modules, not four), because the verify path
  now imports it. The registry also lists the web and Unity adapters, whose runners are not in the
  wheel and are imported only inside their own `run`; neither has a verify path. `tests/test_package.py`
  lists those four imports as ones no verification reaches, with the reason.

For Godot nothing changes: the same replay with the same arguments, the same digest, the same
messages, the same record. A test compares the record made by default with the one made with
`adapter="godot"`.

## What was run

- `python3 -m unittest tests.test_engine_from_adapter`: 31 tests, OK. The same file against main's
  code: 3 failures and 35 errors (counting sub-cases). The second engine in these tests is a
  stand-in adapter whose harness writes the recorded fixture traces the other gate tests use; no
  Godot and no model ran.
- `python3 -m unittest discover -s tests -t .` on this branch (one commit on main at dddced6):
  2,600 tests, OK, 27 skipped.
- `python3 -m unittest tests.test_package`: 17 tests, OK (the wheel is built and installed; a job
  runs from the installed copy on the stand-in replay).
- Not run: real Godot. This machine has none, and the change to the Godot path is which function
  hands `harness.run.run` its arguments; `tests/test_second_project.py`'s real-engine tests run in
  CI's `seeded-bugs` job.

## Not done

- The gate reads the engine's record as a position log of the player and the ground line
  (`agents.observations.from_trace_synthetic`). An engine has to write that log to be judged; the
  observations are not yet the adapter's. That is the Unity half (#324).
- `expectrail.gate.verify`'s command line and the verify action have no `--adapter`; they run
  `godot`. `expectrail verify --adapter` already existed and now reaches the registry.
- `stopped_record` (a run that could not start) still writes `"adapter": "godot"`: it is written
  before any adapter is known.
- `harness.run.run` still falls back to the bundled game when given none. The verify path cannot
  take that fallback (`verify_run` refuses a missing game); the older `agents/` callers still do.
- The `isolated` class's sandbox probe in the preflight is the Godot harness's sandbox for every adapter.

## Files

- `harness/adapters.py`
- `expectrail/gate/verify.py`
- `expectrail/orchestrator/engines.py`, `expectrail/orchestrator/runner.py`, `expectrail/orchestrator/request.py`
- `contracts/findings.schema.json`
- `tests/test_engine_from_adapter.py`, `tests/test_package.py`
- `setup.py`, `docs/install.md`
- `docs/harness.md`, `docs/ci-gate.md`, `docs/orchestrator.md`
