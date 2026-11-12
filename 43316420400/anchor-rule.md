# The anchored rule: what is drawn at the player's place, against a clean run's range

Set on `clean` (13 frames, pad 2 game px, point 14 px above the origin). A probe's rule: no verdict reads it.

| Measure (game px) | From | To |
| --- | --- | --- |
| width | 28.5 | 61 |
| height | 50 | 66.5 |
| above | 24 | 38 |
| below | 23.5 | 39.5 |

| Run | Result | Judged | Out | No answer | Not asked | Why |
| --- | --- | --- | --- | --- | --- | --- |
| clean-coins | pass | 13 | 0 | 0 | 0 | all 13 judged frames are inside the clean range |
| clean-combat | pass | 10 | 0 | 0 | 0 | all 10 judged frames are inside the clean range |
| clean-traversal | fail | 13 | 1 | 0 | 0 | 1 of 13 judged frames are outside the clean range, first frame 20: height 107.5 (clean 50 to 66.5); below 81 (clean 23.5 to 39.5) |
| clean | pass | 13 | 0 | 0 | 0 | all 13 judged frames are inside the clean range |
| layering_v1 | fail | 13 | 9 | 0 | 0 | 9 of 13 judged frames are outside the clean range, first frame 0: height 28 (clean 50 to 66.5); above 8 (clean 24 to 38); below 20 (clean 23.5 to 39.5) |
| layering_v2 | fail | 13 | 9 | 0 | 0 | 9 of 13 judged frames are outside the clean range, first frame 0: height 28 (clean 50 to 66.5); above 8 (clean 24 to 38); below 20 (clean 23.5 to 39.5) |
| missing-texture_v1 | pass | 13 | 0 | 0 | 0 | all 13 judged frames are inside the clean range |
| missing-texture_v2 | pass | 13 | 0 | 0 | 0 | all 13 judged frames are inside the clean range |
| physics-fall-through_v1 | pass | 2 | 0 | 0 | 11 | all 2 judged frames are inside the clean range |
| physics-fall-through_v2 | pass | 2 | 0 | 0 | 11 | all 2 judged frames are inside the clean range |
| sinking_v1 | fail | 13 | 1 | 0 | 0 | 1 of 13 judged frames are outside the clean range, first frame 60: width 73.5 (clean 28.5 to 61) |
| sinking_v2 | fail | 13 | 13 | 0 | 0 | 13 of 13 judged frames are outside the clean range, first frame 0: above 3 (clean 24 to 38); below 56 (clean 23.5 to 39.5) |
