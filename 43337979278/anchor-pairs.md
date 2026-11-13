# The anchored rule, in pairs: each frame against the unchanged game's same frame

Unchanged game: `clean`. Tolerance 6 game px, point 17 px above the origin. A probe's rule: no verdict reads it.

| Run | Result | Compared | Differ | Engine moved | No base | No answer | Not asked | Why |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| clean-coins | needs-review | 0 | 0 | 0 | 0 | 0 | 0 | a different route (coins against smoke): frames of different routes are not compared, and that is not a pass |
| clean-combat | needs-review | 0 | 0 | 0 | 0 | 0 | 0 | a different route (combat against smoke): frames of different routes are not compared, and that is not a pass |
| clean-traversal | needs-review | 0 | 0 | 0 | 0 | 0 | 0 | a different route (traversal against smoke): frames of different routes are not compared, and that is not a pass |
| layering_v1 | fail | 13 | 8 | 0 | 0 | 0 | 0 | 8 of 13 compared frames differ from the unchanged game, first frame 0: width 49 against 38.5 unchanged; above 33.5 against 26.5 unchanged; below 23.5 against 33 unchanged |
| layering_v2 | fail | 13 | 8 | 0 | 0 | 0 | 0 | 8 of 13 compared frames differ from the unchanged game, first frame 0: width 49 against 38.5 unchanged; above 33.5 against 26.5 unchanged; below 23.5 against 33 unchanged |
| missing-texture_v1 | pass | 13 | 0 | 0 | 0 | 0 | 0 | all 13 asked frames agree with the unchanged game within 6 px |
| missing-texture_v2 | pass | 13 | 0 | 0 | 0 | 0 | 0 | all 13 asked frames agree with the unchanged game within 6 px |
| physics-fall-through_v1 | needs-review | 0 | 0 | 2 | 0 | 0 | 11 | the engine puts the player elsewhere in 2 frames; 0 frames were compared and agree, and that is not a pass |
| physics-fall-through_v2 | needs-review | 0 | 0 | 2 | 0 | 0 | 11 | the engine puts the player elsewhere in 2 frames; 0 frames were compared and agree, and that is not a pass |
| sinking_v1 | needs-review | 0 | 0 | 13 | 0 | 0 | 0 | the engine puts the player elsewhere in 13 frames; 0 frames were compared and agree, and that is not a pass |
| sinking_v2 | fail | 13 | 13 | 0 | 0 | 0 | 0 | 13 of 13 compared frames differ from the unchanged game, first frame 0: width 57 against 38.5 unchanged; above 34.5 against 26.5 unchanged; below 25.5 against 33 unchanged |
