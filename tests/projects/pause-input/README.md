# Pause Input: a Godot project that pauses its scene tree

For Expectrail's own tests (`tests/test_pause_input.py`). It shares no file with the bundled game
and is not meant to be a game: a marker named `Player` that walks while `right` is held and stands
still while the tree is paused.

| Action | Bound to | What it does |
| --- | --- | --- |
| `right` | nothing | polled each tick; 2 px a tick while the game runs |
| `pause` | P | read in `_unhandled_input` by the scene's root, which runs while paused; pauses or unpauses the tree |

`routes/pause.json` holds right from tick 2, pauses at 20, unpauses at 40 and releases right at 60.

Before November 13, 2026 the harness itself was paused with the tree: no more presses were sent, no
more rows were recorded, and a route that opened a pause menu never reached its last tick (the
bundled game's pause menu, which shows the coin counter, could not be reached by any route).
