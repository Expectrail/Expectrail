# The ground under the player is read down to the level's last tile row

## What changed
The harness read only 16 tile rows down when it looked for the ground under the player. Platforms that are bodies had no such limit. In Godot's kinematic_character demo the player jumps over a pit, and the floor under the pit is row 29 while the search stopped at row 27. That left 5 frames (ticks 76 to 86) with no ground, so the clean game could only end needs-review (outside trial on #397). The search now goes down to the last row the layer uses. Over a pit with no floor at all there is still no ground.

## What was run
- `tests.test_ground_under` with Godot 4.7.2: 24 tests pass. The new `FarFloorTest` adds one tile 21 rows under the gap. It fails without this change (no ground over the gap) and passes with it (1600, "tile").
- The full suite (below, in the PR).
- The outside trial on #398 ([run 43484520696](https://github.com/Expectrail/Expectrail/actions/runs/43484520696/job/132089304010)): kinematic_character as pinned **accept**, broken **reject** (frame 44, 71.7 px past 304.5), harmless **accept**; dodge_the_creeps needs-review (no ground in any frame).
- The merge guard held #398: the trial's expectation for harmless was still needs-review (the product manager's call 4). On November 13, 2026 Sean withdrew call 4 for the engine's record and said an outside game counts as verified only once vision has looked at it too. This pull request replaces #398 with the expectation, the doc and this log brought up to date.

## Not done
- No check was written for kinematic_character; the trial shows the 5 frames judged.
- No run with vision on an outside project: no outside project counts as verified yet.
- The fall-through case: a player who has fallen more than 64 px through a floor is now measured against the next floor down at any depth, not only within 16 rows. Before this, a floor up to 16 rows down already did the same. The sink is caught on the frames before it passes 64 px, as before.

## Files
- tests/outside/projects.json
- docs/outside-projects.md
- harness/godot/expectrail_harness.gd
- tests/test_ground_under.py
