# The anchored rule: what is drawn at the player's place, against a clean run's range

Set on `clean` (13 frames, pad 2 game px, point 17 px above the origin). A probe's rule: no verdict reads it.

| Measure (game px) | From | To |
| --- | --- | --- |
| width | 29 | 61 |
| height | 51.5 | 65 |
| above | 21 | 35.5 |
| below | 25.5 | 41.5 |

| Run | Result | Judged | Out | No answer | Not asked | Why |
| --- | --- | --- | --- | --- | --- | --- |
| clean | pass | 13 | 0 | 0 | 0 | all 13 judged frames are inside the clean range |
| missing-texture_v1 | pass | 13 | 0 | 0 | 0 | all 13 judged frames are inside the clean range |
| layering_v1 | fail | 13 | 5 | 0 | 0 | 5 of 13 judged frames are outside the clean range, first frame 0: below 23.5 (clean 25.5 to 41.5) |
| sinking_v2 | fail | 13 | 10 | 0 | 0 | 10 of 13 judged frames are outside the clean range, first frame 10: height 79 (clean 51.5 to 65); above 38.5 (clean 21 to 35.5) |
