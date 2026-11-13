# The anchored rule: what is drawn at the player's place, against a clean run's range

Set on `clean` (13 frames, pad 2 game px, point 0 px above the origin). A probe's rule: no verdict reads it.

| Measure (game px) | From | To |
| --- | --- | --- |
| width | 29 | 61 |
| height | 50 | 64.5 |
| above | 24 | 38 |
| below | 23.5 | 38.5 |

| Run | Result | Judged | Out | No answer | Not asked | Why |
| --- | --- | --- | --- | --- | --- | --- |
| clean-coins | pass | 13 | 0 | 0 | 0 | all 13 judged frames are inside the clean range |
| clean-combat | fail | 10 | 1 | 0 | 0 | 1 of 10 judged frames are outside the clean range, first frame 50: height 66.5 (clean 50 to 64.5) |
| clean-traversal | pass | 13 | 0 | 0 | 0 | all 13 judged frames are inside the clean range |
| clean | pass | 13 | 0 | 0 | 0 | all 13 judged frames are inside the clean range |
| layering_v1 | fail | 13 | 7 | 0 | 0 | 7 of 13 judged frames are outside the clean range, first frame 0: height 30.5 (clean 50 to 64.5); above 10 (clean 24 to 38); below 20.5 (clean 23.5 to 38.5) |
| layering_v2 | fail | 13 | 7 | 0 | 0 | 7 of 13 judged frames are outside the clean range, first frame 0: height 30.5 (clean 50 to 64.5); above 10 (clean 24 to 38); below 20.5 (clean 23.5 to 38.5) |
| missing-texture_v1 | pass | 13 | 0 | 0 | 0 | all 13 judged frames are inside the clean range |
| missing-texture_v2 | pass | 13 | 0 | 0 | 0 | all 13 judged frames are inside the clean range |
| physics-fall-through_v1 | pass | 2 | 0 | 0 | 11 | all 2 judged frames are inside the clean range |
| physics-fall-through_v2 | pass | 2 | 0 | 0 | 11 | all 2 judged frames are inside the clean range |
| sinking_v1 | fail | 13 | 10 | 0 | 0 | 10 of 13 judged frames are outside the clean range, first frame 0: height 47 (clean 50 to 64.5); above 11.5 (clean 24 to 38) |
| sinking_v2 | fail | 13 | 11 | 0 | 0 | 11 of 13 judged frames are outside the clean range, first frame 0: below 22.5 (clean 23.5 to 38.5) |
