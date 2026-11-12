# A route drives a game that reads input as events (#338)

## What changed
The Godot harness pressed a route's actions with `Input.action_press`. That sets the action's state
and sends no input event, so only a game that polls its input was driven. A game that reads events
(`_input`, `_unhandled_input`, a button whose shortcut is an action) saw nothing: a menu's Start
button or a pause key was never pressed, and the replay still ended with exit 0 and a full trace.
Found by reading Godot's Dodge the Creeps demo for the outside-project trial (#263): it starts from
a button whose shortcut is an action.

- `harness/godot/expectrail_harness.gd` sends every press and release as an input event and sends it
  on at once (`Input.parse_input_event`, then `Input.flush_buffered_events`), so it arrives on the
  tick the route names. It presses the first key or pad button the project binds to the action; an
  action with neither is sent as an action event. `docs/harness.md`, "How a press is sent", says
  which ways of reading input see which.
- `tests/projects/event-input`: a project written for the test. Four actions, each read a different
  way, each written into the player's position.
- `tests/test_event_input.py`, and a step in the CI job `capture-smoke` that runs it with the real
  engine and a skip counted as a failure.

## What was run
- With main's harness, the new route on the new project: the player is at (100, 100) on all 70
  ticks, exit 0. With the change: started on tick 10, hops on ticks 20 and 30, right released on
  tick 40, the button pressed by its shortcut on tick 50.
- `EXPECTRAIL_ENGINE_TESTS=required python3 -m unittest tests.test_event_input`, Godot 4.7.2 and
  Xvfb here: 8 tests, OK. The replay is run with frames drawn and headless, and the two agree. The
  same tests on main's harness: 5 fail (the four engine tests that expect movement, and the one
  that reads the script).
- The bundled game, routes `smoke`, `coins`, `combat` and `traversal`, replayed with main's harness
  and with this one: `trace.json` and every frame's sha256 are the same, byte for byte, for all four
  (120, 120, 90 and 180 frames). Run twice: once sending action events only, once as merged here.
- `python3 -m unittest discover -s tests -t .` on Python 3.13: 2,130 tests, OK, 22 skipped.
- The real sample (`python3 -m expectrail.orchestrator sample`): accept, reject, accept, each as
  expected.
- Not run here: `harness.check_seeded` (every seeded bug against the clean game); the CI job
  `seeded-bugs` runs it.
- The replays here were not sandboxed: this machine has no bubblewrap.

## Not done
- No outside project was run. Dodge the Creeps was read, not run.
- A mouse click, a key that is no action and an amount on a stick cannot be written in a route.
  That is a change to the route contract, for #329 and #261.
- An action bound only to a mouse button or a stick is sent as an action event, which a button's
  shortcut does not see.
- A route that names an action the project does not have is not stopped; the press goes nowhere.
- The trace does not say how each action was sent.
- Unity's and the web runner's input were not looked at.

## Files
`harness/godot/expectrail_harness.gd`, `tests/projects/event-input/` (`README.md`,
`project/project.godot`, `project/main.tscn`, `project/main.gd`, `routes/events.json`),
`tests/test_event_input.py`, `.github/workflows/ci.yml`, `docs/harness.md`
