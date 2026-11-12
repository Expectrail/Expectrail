# The anchored rule, in pairs: each frame against the unchanged game's same frame

Unchanged game: `clean`. Tolerance 6 game px, point 14 px above the origin. A probe's rule: no verdict reads it.

| Run | Result | Compared | Differ | Engine moved | No base | No answer | Not asked | Why |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| missing-texture_v1 | fail | 13 | 1 | 0 | 0 | 0 | 0 | 1 of 13 compared frames differ from the unchanged game, first frame 100: width 113 against 58.5 unchanged; height 91 against 60.5 unchanged; below 59 against 28 unchanged |
| layering_v1 | fail | 13 | 8 | 0 | 0 | 0 | 0 | 8 of 13 compared frames differ from the unchanged game, first frame 0: height 28 against 59 unchanged; above 8 against 29 unchanged; below 20 against 30 unchanged |
| sinking_v2 | fail | 13 | 13 | 0 | 0 | 0 | 0 | 13 of 13 compared frames differ from the unchanged game, first frame 0: above 3 against 29 unchanged; below 56 against 30 unchanged |
