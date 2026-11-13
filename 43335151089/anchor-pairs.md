# The anchored rule, in pairs: each frame against the unchanged game's same frame

Unchanged game: `clean`. Tolerance 6 game px, point 17 px above the origin. A probe's rule: no verdict reads it.

| Run | Result | Compared | Differ | Engine moved | No base | No answer | Not asked | Why |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| missing-texture_v1 | pass | 13 | 0 | 0 | 0 | 0 | 0 | all 13 asked frames agree with the unchanged game within 6 px |
| layering_v1 | fail | 13 | 6 | 0 | 0 | 0 | 0 | 6 of 13 compared frames differ from the unchanged game, first frame 0: width 49 against 38.5 unchanged; above 33.5 against 26.5 unchanged; below 23.5 against 33 unchanged |
| sinking_v2 | fail | 13 | 12 | 0 | 0 | 0 | 0 | 12 of 13 compared frames differ from the unchanged game, first frame 0: width 57 against 38.5 unchanged; above 34.5 against 26.5 unchanged; below 25.5 against 33 unchanged |
