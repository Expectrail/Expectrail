# The gate's command takes `--adapter`, and a stopped run records the adapter it asked for (#251)

## What changed
- `python3 -m expectrail.gate.verify` has `--adapter` (default `godot`), passed to `run_gate`, which
  asks the registry (`harness/adapters.py`). Before, the command always ran `godot`; `expectrail verify
  --adapter` already reached the registry.
- `stopped_record` (a run that could not start or crashed) wrote `"adapter": "godot"` whatever was
  asked. It now writes the registry's name for a registered adapter and `unknown` for anything else
  (an unregistered name, a wrong type), so a stopped run on another engine is never recorded as a
  Godot run. It never raises: it is written because something already went wrong.
- `--game`'s help says "the project folder", not "the Godot project folder".
- `docs/harness.md` says so.

This changes who is named in a record that is already needs-review; no decision changes, and no new
path to an accept exists.

## What was run
- `python3 -m unittest tests.test_engine_from_adapter tests.test_gate_intent tests.test_two_observers tests.test_ci_gate`:
  195 tests, OK.
- The five new tests (`CommandLineTest`) against main's `verify.py`: 9 errors (the flag did not exist,
  and stopped records said `godot`). With the change: OK. They use the stand-in `probe` engine; no Godot
  and no model ran.
- The full suite: see the pull request.

## Not done
- The verify action stays Godot-only: it installs Godot. Another engine needs its own install step.
- From #251's list, left to other issues: observations that are the adapter's (with Unity, #324,
  paused); a visual observer by default (#327, #379); the `harness.run.run` fallback to the bundled game,
  which the verify path cannot take but the older `agents/` callers still use.

## Files
- `expectrail/gate/verify.py`
- `tests/test_engine_from_adapter.py`
- `docs/harness.md`
- `docs/new-work/2026-11-13-gate-adapter-flag.md`
