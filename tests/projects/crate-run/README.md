# Crate Run: a second Godot project for Expectrail's own tests

A crate walks and jumps on a flat floor. It exists so that the verify path is run on a Godot project
that is not the bundled game (#251). It shares no file with the bundled game, and nothing here is
meant to be a good game.

| Folder | Holds |
| --- | --- |
| `project/` | The Godot 4 project: `main.tscn`, `main.gd` (builds the tile floor in code), `player.gd`, `crate.svg` (the texture the player binding names), `expectrail.project.json`. |
| `routes/walk.json` | One route: walk right, jump twice, stop. 150 ticks at this project's 60 physics ticks a second. |
| `specs/crate-stays-above-floor.json` | A draft spec. Nobody has approved it, so it judges nothing. |

`tests/test_second_project.py` copies these into a checkout and verifies it:

```
expectrail verify --head CHECKOUT --game project --routes routes/walk.json --specs specs
```

## What the tests judge it with

The approved spec that ships with Expectrail (`agents/specs/player-stays-above-ground.json`: "The
player never falls through the ground"), copied unchanged into the checkout's `specs/`. This
project's own spec is a draft; approving it is a person's step.

## What it has in common with the bundled game, on purpose

The harness finds the player by the node name `Player` and the ground by the collision of
`TileMapLayer` tiles, so this project has both. `project/expectrail.project.json` names that node
and the texture `res://crate.svg`, and the project's 60 physics ticks a second. The player's size
is not in that file: a trace row's `body` is the crate's own collision box. A trace from before
the harness logged `body` still uses the bundled constants (40 by 60, feet 13.25 below the origin).

## What is different

Its own input actions (`left`, `right`, `jump`), 60 physics ticks a second where the bundled game
has 120, a 640 by 360 window, no enemies, no coins. The bundled game has no project config yet.
