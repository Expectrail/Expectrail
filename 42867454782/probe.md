# SAM probe: player-stays-above-ground

Model `sam-3.1`. Prompts: player = "blue robot", ground = "grass-topped ground". API calls 160, cache hits 74.

Verdicts below are on the probed frames only, not a full run.

| Run | Frames | Verdict | player found | ground found |
| --- | --- | --- | --- | --- |
| clean | 13 | needs-review | 13/13 | 0/13 |
| layering_v1 | 13 | needs-review | 7/13 | 0/13 |
| layering_v2 | 13 | needs-review | 7/13 | 0/13 |
| missing-texture_v1 | 13 | needs-review | 13/13 | 0/13 |
| missing-texture_v2 | 13 | needs-review | 13/13 | 0/13 |
| physics-fall-through_v1 | 13 | needs-review | 3/13 | 0/13 |
| physics-fall-through_v2 | 13 | needs-review | 3/13 | 0/13 |
| sinking_v1 | 13 | needs-review | 13/13 | 0/13 |
| sinking_v2 | 13 | needs-review | 13/13 | 0/13 |

## Per object

**clean**: no violation in 0 frames judged, but an object was not found in 13 frames (first 0); a missing object is never a pass
- player: best score min 0.82, median 0.92, max 0.96; matches per frame 1 to 1; box width {'min': 62.0, 'median': 95.0, 'max': 118.0}, height {'min': 102.0, 'median': 118.0, 'max': 126.0}
- ground: best score min 0.00, median 0.00, max 0.00; matches per frame 0 to 0; box width None, height None

**layering_v1**: no violation in 0 frames judged, but an object was not found in 13 frames (first 0); a missing object is never a pass
- player: best score min 0.00, median 0.60, max 0.95; matches per frame 0 to 1; box width {'min': 64.0, 'median': 117.0, 'max': 118.0}, height {'min': 61.0, 'median': 121.0, 'max': 122.0}
- ground: best score min 0.00, median 0.00, max 0.00; matches per frame 0 to 0; box width None, height None

**layering_v2**: no violation in 0 frames judged, but an object was not found in 13 frames (first 0); a missing object is never a pass
- player: best score min 0.00, median 0.60, max 0.95; matches per frame 0 to 1; box width {'min': 64.0, 'median': 117.0, 'max': 118.0}, height {'min': 61.0, 'median': 121.0, 'max': 122.0}
- ground: best score min 0.00, median 0.00, max 0.00; matches per frame 0 to 0; box width None, height None

**missing-texture_v1**: no violation in 0 frames judged, but an object was not found in 13 frames (first 0); a missing object is never a pass
- player: best score min 0.84, median 0.92, max 0.96; matches per frame 1 to 1; box width {'min': 62.0, 'median': 95.0, 'max': 118.0}, height {'min': 102.0, 'median': 118.0, 'max': 126.0}
- ground: best score min 0.00, median 0.00, max 0.00; matches per frame 0 to 0; box width None, height None

**missing-texture_v2**: no violation in 0 frames judged, but an object was not found in 13 frames (first 0); a missing object is never a pass
- player: best score min 0.84, median 0.92, max 0.96; matches per frame 1 to 1; box width {'min': 62.0, 'median': 95.0, 'max': 118.0}, height {'min': 102.0, 'median': 118.0, 'max': 126.0}
- ground: best score min 0.00, median 0.00, max 0.00; matches per frame 0 to 0; box width None, height None

**physics-fall-through_v1**: no violation in 0 frames judged, but an object was not found in 13 frames (first 0); a missing object is never a pass
- player: best score min 0.00, median 0.00, max 0.95; matches per frame 0 to 1; box width {'min': 80.0, 'median': 117.0, 'max': 118.0}, height {'min': 47.0, 'median': 122.0, 'max': 122.0}
- ground: best score min 0.00, median 0.00, max 0.00; matches per frame 0 to 0; box width None, height None

**physics-fall-through_v2**: no violation in 0 frames judged, but an object was not found in 13 frames (first 0); a missing object is never a pass
- player: best score min 0.00, median 0.00, max 0.94; matches per frame 0 to 1; box width {'min': 81.0, 'median': 117.0, 'max': 118.0}, height {'min': 47.0, 'median': 122.0, 'max': 122.0}
- ground: best score min 0.00, median 0.00, max 0.00; matches per frame 0 to 0; box width None, height None

**sinking_v1**: no violation in 0 frames judged, but an object was not found in 13 frames (first 0); a missing object is never a pass
- player: best score min 0.62, median 0.91, max 0.96; matches per frame 1 to 1; box width {'min': 73.0, 'median': 100.0, 'max': 118.0}, height {'min': 105.0, 'median': 122.0, 'max': 127.0}
- ground: best score min 0.00, median 0.00, max 0.00; matches per frame 0 to 0; box width None, height None

**sinking_v2**: no violation in 0 frames judged, but an object was not found in 13 frames (first 0); a missing object is never a pass
- player: best score min 0.62, median 0.91, max 0.96; matches per frame 1 to 1; box width {'min': 73.0, 'median': 93.0, 'max': 118.0}, height {'min': 101.0, 'median': 121.0, 'max': 127.0}
- ground: best score min 0.00, median 0.00, max 0.00; matches per frame 0 to 0; box width None, height None

## Tolerance

Approved spec: tolerancePx = 20 (set against the position-log stand-in, whose boxes are in game-world pixels; SAM boxes are in captured-frame pixels, twice as large here).

- clean (clean): worst gap n/a px
- layering_v1 (bug): worst gap n/a px
- layering_v2 (bug): worst gap n/a px
- missing-texture_v1 (bug): worst gap n/a px
- missing-texture_v2 (bug): worst gap n/a px
- physics-fall-through_v1 (bug): worst gap n/a px
- physics-fall-through_v2 (bug): worst gap n/a px
- sinking_v1 (bug): worst gap n/a px
- sinking_v2 (bug): worst gap n/a px

A gap above the tolerance is a fail. The tolerance has to sit above every clean gap and below the gaps of the bugs this spec should catch; no clean run was probed.
