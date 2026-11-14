# A first route from a Godot input map

```sh
expectrail route --project game/platformer --auto --out routes/first.json
expectrail route --project tests/projects/crate-run/project --auto --out routes/crate-first.json
```

In a clone, `python3 -m expectrail.cli route` runs the same command. `--project` is the directory
containing `project.godot`; `--out` must be a new file. The project is copied by the harness,
never edited. No model or model key is used. The existing harness's Godot installation, import
cache and sandbox settings apply. These replays run headless, without a display server.

The command reads the project's `[input]` actions, including explicitly configured `ui_*`
actions. Only an empty or absent input map falls back to `ui_left`, `ui_right`, `ui_up`,
`ui_down` and `ui_accept`. It does not add these built-ins alongside project-defined actions.

The pattern is fixed, with seed 1 passed to the harness and game:

- Movement actions first, alphabetically: hold each for one second.
- Other actions alphabetically: press each three times, for about 0.1 seconds per press.
- Pause about 0.25 seconds initially and between presses, and about 0.5 seconds at the end.

Durations use the project's `physics/common/physics_ticks_per_second` setting (default 60),
rounded to whole ticks with a minimum of one. Movement is a name-based guess: words `move`,
`walk`, `run`, `strafe`, `left`, `right`, `up`, `down`, `forward`, `backward` or `back`, including
camel-case names such as `moveRight`. Other names still get exercised as short presses.
Actions that share a physical binding may fire together, as they do with real input.
The harness clock continues while the game is paused; game nodes keep their own pause modes.

The candidate uses the existing `expectrail.route/v0` contract. See
[the schema](../contracts/route.schema.json) and [the crate-run example](../contracts/examples/auto-route.json).
It is replayed three times before the destination file is created. Every trace field is compared:
every tick's complete row, plus metadata. Missing ticks, malformed traces, an interrupted replay,
or a project that changes between runs cannot produce a saved route. An existing output is never
overwritten, including one created while the checks are running.

When traces differ, the command reports the differing zero-based ticks (inclusive ranges), any
differing metadata fields, and says the project is not yet deterministic under the harness. No
route is written. A seed does not control an independently randomized source; three matching
runs are evidence for this route on this machine, not proof that every path in the game is deterministic.
Rendered frames are not captured or compared.

The summary lists actions, press counts, durations and pauses. It also says whether the harness's
bound `Player` node moved at any point, even if it returned to its starting position. An absent
player means movement is unknown. A stationary player is reported as lacking demonstrated useful
movement coverage. Empty input coverage is reported separately. A deterministic route can be saved
even when movement is absent: inspect the summary before treating it as useful. Gravity alone can
move a player; movement does not prove that every action worked. Binding another player node and
inventing game-specific routes are outside this command.

Exit codes: **0** saved; **2** differing traces, needs review; **5** invalid arguments, unusable
project/replay, or an output that cannot be written. Candidate routes and replay copies are temporary.
