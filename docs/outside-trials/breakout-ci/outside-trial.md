| Project | Change | Exit | Verdict | Expected | Seconds | Checks | Reasons |
| --- | --- | --- | --- | --- | --- | --- | --- |
| breakout (`0ac7aed`, MIT) | none (the project as pinned) | 2 | needs-review | needs-review (as expected) | 58.3 | none | TOOL_MISSING: 33 MB free in the engine's folder ($REPO/tools). Fix: free at least 1024 MB in each folder named above, or name other folders with EXPECTRAIL_TOOLS and TMPDIR |
| breakout (`0ac7aed`, MIT) | harmless: a comment only; both draft diagnostics pass; drafts cannot clear a change | 2 | needs-review | needs-review (as expected) | 59.8 | none | TOOL_MISSING: 33 MB free in the engine's folder ($REPO/tools). Fix: free at least 1024 MB in each folder named above, or name other folders with EXPECTRAIL_TOOLS and TMPDIR |
| breakout (`0ac7aed`, MIT) | broken: paddle is forced to x=8; raw paddle draft fails, ball movement checkpoint is not reached; unapproved drafts do not reject at the gate | 2 | needs-review | needs-review (as expected) | 50.7 | none | TOOL_MISSING: 33 MB free in the engine's folder ($REPO/tools). Fix: free at least 1024 MB in each folder named above, or name other folders with EXPECTRAIL_TOOLS and TMPDIR |

Draft engine diagnostics for breakout / pinned (unapproved; do not change the gate verdict):

- breakout-paddle-bounds on auto-input-map: pass; no violation in 51 frames; first checked failure None.
- breakout-ball-starts on auto-input-map: pass; no violation in 11 frames; first checked failure None.
- auto-input-map: Route: 407 physics ticks (6.78333 seconds at 60 ticks/second), seed 1.
- auto-input-map:   pointer left click at viewport [180.0, 290.0]: move tick 12; left down tick 13; left up tick 14.
- auto-input-map:   pointer sweep in viewport [177.6, 293.7] to [36.0, 512.0], ticks 17–76 (60 recorded moves).
- auto-input-map:   pointer sweep in viewport [40.8, 512.0] to [324.0, 512.0], ticks 92–151 (60 recorded moves).
- auto-input-map:   pointer sweep in viewport [319.2, 512.0] to [36.0, 512.0], ticks 167–226 (60 recorded moves).
- auto-input-map:   pointer sweep in viewport [40.8, 512.0] to [324.0, 512.0], ticks 242–301 (60 recorded moves).
- auto-input-map:   pointer sweep in viewport [321.6, 512.0] to [180.0, 512.0], ticks 317–376 (60 recorded moves).
- auto-input-map: The bound player (Player) moved during the replay. Movement alone does not prove the actions caused it.

Draft engine diagnostics for breakout / harmless (unapproved; do not change the gate verdict):

- breakout-paddle-bounds on auto-input-map: pass; no violation in 51 frames; first checked failure None.
- breakout-ball-starts on auto-input-map: pass; no violation in 11 frames; first checked failure None.
- auto-input-map: Route: 407 physics ticks (6.78333 seconds at 60 ticks/second), seed 1.
- auto-input-map:   pointer left click at viewport [180.0, 290.0]: move tick 12; left down tick 13; left up tick 14.
- auto-input-map:   pointer sweep in viewport [177.6, 293.7] to [36.0, 512.0], ticks 17–76 (60 recorded moves).
- auto-input-map:   pointer sweep in viewport [40.8, 512.0] to [324.0, 512.0], ticks 92–151 (60 recorded moves).
- auto-input-map:   pointer sweep in viewport [319.2, 512.0] to [36.0, 512.0], ticks 167–226 (60 recorded moves).
- auto-input-map:   pointer sweep in viewport [40.8, 512.0] to [324.0, 512.0], ticks 242–301 (60 recorded moves).
- auto-input-map:   pointer sweep in viewport [321.6, 512.0] to [180.0, 512.0], ticks 317–376 (60 recorded moves).
- auto-input-map: The bound player (Player) moved during the replay. Movement alone does not prove the actions caused it.

Draft engine diagnostics for breakout / broken (unapproved; do not change the gate verdict):

- breakout-paddle-bounds on auto-input-map: fail; player [-15.5, 607.0, 31.5, 625.0] leaves region [0, 0, 360.0, 640.0] (first at frame 20, 51 frames); first checked failure 20.
- breakout-ball-starts on auto-input-map: needs-review; not-exercised: 11 judged frames; needs 11; observed 11 of 11 window frames; checkpoint not-reached; no violation in 11 frames; first checked failure None.
- auto-input-map: Route: 407 physics ticks (6.78333 seconds at 60 ticks/second), seed 1.
- auto-input-map:   pointer left click at viewport [180.0, 290.0]: move tick 12; left down tick 13; left up tick 14.
- auto-input-map:   pointer sweep in viewport [177.6, 293.7] to [36.0, 512.0], ticks 17–76 (60 recorded moves).
- auto-input-map:   pointer sweep in viewport [40.8, 512.0] to [324.0, 512.0], ticks 92–151 (60 recorded moves).
- auto-input-map:   pointer sweep in viewport [319.2, 512.0] to [36.0, 512.0], ticks 167–226 (60 recorded moves).
- auto-input-map:   pointer sweep in viewport [40.8, 512.0] to [324.0, 512.0], ticks 242–301 (60 recorded moves).
- auto-input-map:   pointer sweep in viewport [321.6, 512.0] to [180.0, 512.0], ticks 317–376 (60 recorded moves).
- auto-input-map: The bound player (Player) moved during the replay. Movement alone does not prove the actions caused it.
