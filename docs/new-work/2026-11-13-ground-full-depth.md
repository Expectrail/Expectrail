# The ground under the player is read down to the level's last tile row

## What changed
The harness read only 16 tile rows down when it looked for the ground under the player. Platforms that are bodies had no such limit. In Godot's kinematic_character demo the player jumps over a pit, and the floor under the pit is row 29 while the search stopped at row 27. That left 5 frames (ticks 76 to 86) with no ground, so the clean game could only end needs-review (outside trial on #397). The search now goes down to the last row the layer uses. Over a pit with no floor at all there is still no ground.

## What was run
- `tests.test_ground_under` with Godot 4.7.2: 24 tests pass. The new `FarFloorTest` adds one tile 21 rows under the gap. It fails without this change (no ground over the gap) and passes with it (1600, "tile").
- The full suite (below, in the PR).
- The outside trial has not run on this yet. CI's run on the pull request is the first.

## Not done
- No check was written for kinematic_character, and none is needed if the trial shows the 5 frames judged.
- The fall-through case: a player who has fallen more than 64 px through a floor is now measured against the next floor down at any depth, not only within 16 rows. Before this, a floor up to 16 rows down already did the same. The sink is caught on the frames before it passes 64 px, as before.

## Files
- harness/godot/expectrail_harness.gd
- tests/test_ground_under.py
