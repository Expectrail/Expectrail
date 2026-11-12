# Crate Run: a second Godot project for Expectrail's own tests

A crate walks and jumps on a flat floor. It exists so that the verify path is run on a Godot project
that is not the bundled game (#251). It shares no file with the bundled game, and nothing here is
meant to be a good game.

| Folder | Holds |
| --- | --- |
| `project/` | The Godot 4 project: `main.tscn`, `main.gd` (builds the tile floor in code, so there is no image file), `player.gd`. |
| `routes/walk.json` | One route: walk right, jump twice, stop. 150 ticks at this project's 60 physics ticks a second. |
| `specs/crate-stays-above-floor.json` | A draft spec. Nobody has approved it, so it judges nothing. |

`tests/test_second_project.py` copies these into a checkout and verifies it:

```
python3 -m expectrail.orchestrator verify --head CHECKOUT --game project \
    --routes routes/walk.json --specs specs
```

## What the tests judge it with

The approved spec that ships with Expectrail (`agents/specs/player-stays-above-ground.json`: "The
player never falls through the ground"), copied unchanged into the checkout's `specs/`. This
project's own spec is a draft; approving it is a person's step.

## What it has in common with the bundled game, on purpose

The harness finds the player by the node name `Player` and the ground by the collision of
`TileMapLayer` tiles, so this project has both. The position log draws the player's box at the
bundled game's size (40 by 60 pixels, bottom 13.25 below the node's origin). The crate is 32 by 32
with its bottom 16 below its origin, so the box the check sees ends 2.75 pixels above the crate's
real bottom. The check's tolerance is 20 pixels. Sizes move out of code in #259.

## What is different

Its own input actions (`left`, `right`, `jump`), 60 physics ticks a second where the bundled game
has 120, a 640 by 360 window, no sprite, no enemies, no coins.
