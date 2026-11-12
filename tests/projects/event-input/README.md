# Event Input: a Godot project that reads input as events

For Expectrail's own tests (`tests/test_event_input.py`). It shares no file with the bundled game
and is not meant to be a game: a marker named `Player` whose position records what input arrived.

| Action | Bound to | How the game reads it | What it does |
| --- | --- | --- | --- |
| `start` | Enter | an event in `_unhandled_input` | nothing moves before it |
| `hop` | nothing | an event in `_input` | each press lifts the player 8 px |
| `right` | nothing | polled each tick with `Input.is_action_pressed` | 2 px a tick, once started |
| `menu` | M | the shortcut of a button | the button's press drops the player to y = 300 |

`routes/events.json` holds right from tick 2, starts at tick 10, hops at 20 and 30, releases right
at 40 and opens the menu at 50. The test holds the player's position at those ticks.

The harness sends each press as the key the project binds to the action, when it binds one, and as
an action event otherwise. The engine offers only key and pad-button events to a button's shortcut,
so an action with no key cannot press a button that way: `hop` here is read in `_input`, where an
action event does arrive.
