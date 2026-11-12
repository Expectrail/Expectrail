# The anchored rule: what is drawn at the player's place, against a clean run's range

Set on `clean` (13 frames, pad 2 game px, point 14 px above the origin). A probe's rule: no verdict reads it.

| Measure (game px) | From | To |
| --- | --- | --- |
| width | 29 | 61.5 |
| height | 51.5 | 109.5 |
| above | 24 | 38.5 |
| below | 22.5 | 83 |

| Run | Result | Judged | Out | No answer | Not asked | Why |
| --- | --- | --- | --- | --- | --- | --- |
| clean | pass | 13 | 0 | 0 | 0 | all 13 judged frames are inside the clean range |
| missing-texture_v1 | fail | 13 | 1 | 0 | 0 | 1 of 13 judged frames are outside the clean range, first frame 100: width 113 (clean 29 to 61.5) |
| layering_v1 | fail | 13 | 8 | 0 | 0 | 8 of 13 judged frames are outside the clean range, first frame 0: height 28 (clean 51.5 to 109.5); above 8 (clean 24 to 38.5); below 20 (clean 22.5 to 83) |
| sinking_v2 | fail | 13 | 13 | 0 | 0 | 13 of 13 judged frames are outside the clean range, first frame 0: above 3 (clean 24 to 38.5) |
