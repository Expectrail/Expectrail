# Which bounds and movement checks does the public Breakout route support? (#716)

The paddle's height in the playfield supports a tighter draft drawing region. Its horizontal travel on this route gives no basis for contracting the sides to the sampled range. The Ball moves by about 66.7 pixels in ten ticks of the launch window, but the existing named-position coverage evaluator cannot read the Ball binding. The decision for a missing Ball witness is **needs-review**. The results below are advisory engine diagnostics for one public route and seed. [Current drafts and route](../../../tests/outside/breakout-pointer/) · [Published clean trace](../breakout-pointer/trial-evidence/pinned-1/trace.json)

## Paddle geometry

Coordinates are game pixels, increasing right and down, in a 360 × 640 viewport. The replay's view transform was the identity throughout. The table gives the envelope of the boxes, with endpoints in left, top, right, bottom order. The harness measures the authored sprite rectangle, including transparent pixels.

| Godot 4.6.3 clean replay | Paddle centre x | Drawing envelope | Collision envelope |
| --- | --- | --- | --- |
| Draft window, ticks 20–70 inclusive | 49.440–170.332 | [25.940, 607, 193.832, 625] | [25.440, 606, 194.332, 625] |
| Full route, ticks 0–406 | 35.040–188.000 | [11.540, 607, 211.500, 625] | [11.040, 606, 212.000, 625] |

The scene starts the paddle at (168, 616). Its centred atlas frame is 47 × 18. Its collider is 48 × 19, offset by (0, −0.5), giving a top one pixel above the drawing. The controller sets vertical velocity to zero and the Ball restores the initial paddle height on paddle contact. The baseline draft at `990cf8d` evaluated the drawing against the full viewport. The revised draft region **[0, 606, 360, 625]** uses the collider’s vertical envelope around the drawing. That leaves one pixel of room above the drawing and none below. An exact-art region would start at 607. This route exercised horizontal movement and a miss. Paddle contact and changes of level were not exercised. [Geometry and pinned sources](derivation.json)

Horizontally the controller clamps its **target centre** to 24–336. A paddle centred at those targets would draw from 0.5 on the left to 359.5 on the right. The side-wall faces are at −0.25 and 360.25. At ideal wall contact the corresponding centre limits are 23.75 and 336.25, with the drawing inset 0.5 pixels from the collision sides. Actual motion uses velocity proportional to the target error and `move_and_slide()`. The centre can overshoot the pointer target, as it did on release at tick 14 (pointer x=180, centre x=188). The clean run sampled neither wall limit. The revised draft retains the full viewport width. Rounding, solver margins and contact at the extremes make a subpixel tightening a separate question. [Paddle controller and wall geometry](derivation.json)

## Ball launch and miss

The ball starts at (216, 200). Its circular collider has radius **4**, and its 4 × 4 texture at scale 2 gives an 8 × 8 drawing. The level-one launch speed is 400 px/s, initially down within ±45°. The release at tick 14 started a downward-right launch with seed 1. Midpoints of the Ball's drawing boxes were identical on all 407 ticks of the new 4.6.3 headless replay and the published 4.7.2 rendered replay. The paddle x values differed slightly between runs. [Pinned Ball source](derivation.json) · [Published replay metadata](../breakout-pointer/trial-evidence/pinned-1/replay.json)

| Tick | Ball centre (x, y) | Significance |
| ---: | --- | --- |
| 13 | (216, 200) | Last sample at spawn |
| 14 | (217.764, 206.429) | First sample after Start released |
| 40 | (263.617, 373.588) | Drawing top 369.588, already below the draft line y=204 |
| 50 | (281.254, 437.879) | End of the 11-frame window |
| 76 | (327.107, 605.037) | Drawing bottom 609.037 first passed the paddle top at 607 |
| 81 | (335.926, 637.183) | Drawing bottom 641.183 first passed the viewport bottom |
| 82–406 | (337.689, 643.612) | Centre passed y=640 and the game paused at Game Over |

At tick 76 the ball occupied x=323.107–331.107 and the paddle x=11.540–58.540. There were zero horizontal overlaps in the 331 ticks with the ball bottom below the paddle top. The drawing crossed the viewport bottom on 326 ticks, including the paused tail. It crossed neither side nor the top. An unconditional above-paddle test or a four-sided containment test across this route would flag a legitimate miss. An interaction check needs a route with a witnessed hit and rebound. Side and top wall responses also need positive contact evidence. [Game-over logic](https://github.com/mike0697/Breakout/blob/0ac7aed444ea593a023d9b666c211d7ab8acd51e/scripts/game_manager.gd)

## Can the current coverage evaluator witness Ball movement?

The saved Ball draft checks the drawing against y=204 on frames 40–50. Its two coverage checkpoints read the **Paddle** at ticks 20 and 70. To test the difference, the diagnostic below holds only the Ball drawing fixed in copies of the published clean trace. The recorded Paddle keeps moving. These two counterfactuals are synthetic trace inputs. Only the clean run is gameplay.

| Input | Existing Ball draft | Same draft plus two temporary Ball checkpoints | Distances from the two Ball checkpoint centres |
| --- | --- | --- | --- |
| Published clean | pass | needs-review | 0, 0 px |
| Ball held at spawn | fail | fail | 180.000, 246.667 px |
| Ball held from tick 40 | pass | needs-review | 0, 66.666 px |

The two temporary `position-at-tick` witnesses use the measured Ball centres at ticks 40 and 50, each with a 4 px Euclidean tolerance. Their tolerance discs are disjoint. A single frozen centre cannot satisfy both. These seed-specific centres illustrate what the measurements can distinguish. They would overfit an arbitrary launch angle. A source-grounded candidate for future work is to witness downward displacement of the same Ball after Start, before an opportunity for contact.

Both temporary witnesses validate as test-spec input. Both return unknown on all three traces. The evaluator reads the bound player or an identified enemy or projectile. The public trace records Ball in `roleObjects`, with no tracked projectiles. The region coverage checkpoint also reads the player. Supporting a Ball checkpoint through this binding would require evaluator support. The existing assertion already fails a Ball held at spawn because it can see the drawing above the required line. A Ball held anywhere below that line throughout the assertion window can satisfy that assertion while the Paddle satisfies its own checkpoints. [Coverage evaluator](../../../expectrail/coverage.py) · [Ball draft](../../../tests/outside/breakout-pointer/checks/breakout-ball-starts.json)

## Rendered controls for the revised draft

Each row below is three independent executions of the 407-tick route with Godot 4.6.3 and the existing draft evaluator. Each execution rendered 407 frames using OpenGL and Mesa llvmpipe on Xvfb. The three traces in each row had identical SHA-256 digests. The game pin, input route and seed were held fixed except for the explicitly named control. Local Bubblewrap could not create its user namespace, so these are diagnostic engine observations. Both specs are drafts.

| Public input | Revised paddle draft, 3/3 | Existing Ball draft, 3/3 | Trace SHA-256 prefix |
| --- | --- | --- | --- |
| Pinned game | pass | pass | `8b81d23fed06` |
| Registered harmless edit | pass | pass | `8b81d23fed06` |
| Registered paddle escape | fail at frame 20 | needs-review | `74cfb0da15b1` |
| All route input removed | needs-review | fail at frame 40 | `7416a165bc45` |

With all events removed, Start was never pressed. The paddle stayed at its starting point and missed its movement checkpoints. The ball stayed above the required boundary, which supplied a concrete failure in the first checked frame. The registered paddle escape also failed in its first checked frame despite missing its checkpoints.

The drawing-only regression moves one paddle observation two pixels up or down at frame 35 of the published clean trace. Both positions are well inside the old viewport rectangle. The old draft passed both. The revised draft fails both at frame 35 while the original trace still passes. [Regression test](../../../tests/test_breakout_paddle_rail.py)

## Reproduce

To reproduce the baseline, run from the Expectrail repository at `990cf8dfb47b095ede4394086c2f7fed5ebf52f8` with Python 3.12.14 and Godot `4.6.3.stable.official.7d41c59c4` on PATH. Set `BREAKOUT` to a local checkout of the public upstream. This copies the exact archived commit into a temporary directory, adds the registered public inputs and runs the existing harness with `--headless --audio-driver Dummy --fixed-fps 60`. Configured physics rate was 60 ticks/s, route seed 1, with 407 rows and zero PNGs. Automatic sandbox selection reported a read-only uid map and used diagnostic execution. Godot exited 0 and logged two resources still in use at exit. The new run's trace SHA-256 was `82cdea3d1c08ff6c804817c66b0dc2f05bea77be80ce53b23fa5674431ac6a4d`.

```sh
export RUN=$(mktemp -d)
mkdir -p "$RUN/game" "$RUN/tmp" "$RUN/xdg"
git -C "$BREAKOUT" archive 0ac7aed444ea593a023d9b666c211d7ab8acd51e | tar -x -C "$RUN/game"
cp -r tests/outside/breakout-pointer/. "$RUN/game/"
export EXPECTRAIL_GODOT=$(command -v godot) EXPECTRAIL_TOOLS="$RUN/tools" TMPDIR="$RUN/tmp"
export XDG_DATA_HOME="$RUN/xdg" XDG_CONFIG_HOME="$RUN/xdg" XDG_CACHE_HOME="$RUN/xdg"
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
from pathlib import Path
from harness.run import run
import os
root = Path(os.environ["RUN"])
game = root / "game"
result = run(game / "routes/pointer-auto.json", root / "clean", game=game,
             fps=None, capture_frames=False, sandbox="auto")
print(result["trace"], result["capture"])
PY
```

For the control table, use the published frame-indexed trace. Each temporary hold copies the Ball boxes from one tick onward and retains the original coverage evidence for the Paddle. The diagnostic constructs each candidate in memory.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from math import dist
import json
from expectrail.contracts import validate
from expectrail.coverage import checkpoint
from expectrail.evaluator import evaluate
from expectrail.gate.verify import observations, window_frames

def ball(row):
    return next(o for o in row["roleObjects"] if o["role"] == "ball")

def centre(box):
    return [(box[0] + box[2])/2, (box[1] + box[3])/2]

saved = Path("docs/outside-trials/breakout-pointer/trial-evidence/pinned-1")
source = json.loads((saved / "trace.json").read_text())
digest = sha256((saved / "replay.json").read_bytes()).hexdigest()
draft = json.loads(Path("tests/outside/breakout-pointer/checks/breakout-ball-starts.json").read_text())
augmented = deepcopy(draft)
witnesses = []
for tick in (40, 50):
    x, y = centre(ball(source["rows"][tick])["worldBox"])
    witnesses.append(dict(type="position-at-tick", object="ball", tick=tick, x=x, y=y, tolerancePx=4))
augmented["coverage"]["reached"].extend(witnesses)
print(validate(augmented))
for hold in (None, 0, 40):
    trace = deepcopy(source)
    if hold is not None:
        for row in trace["rows"][hold:]:
            for key in ("box", "worldBox"):
                ball(row)[key] = ball(source["rows"][hold])[key]
    obs = observations(trace, digest)
    for spec in (draft, augmented):
        v = evaluate(spec, obs, trace=trace, route="auto-input-map", capture_fps=60,
                     expected_frames=window_frames(spec, 407, trace, 60))
        print(hold, v["result"], v["coverage"]["semanticResult"])
    for w in witnesses:
        xy = centre(ball(trace["rows"][w["tick"]])["worldBox"])
        print(w["tick"], checkpoint(w, trace), round(dist(xy, [w["x"], w["y"]]), 3))
PY
```

For the revised paddle draft, use the same upstream pin with this PR's public registry. The following diagnostic requires Godot and a working display for rendering. Set `BREAKOUT` to a clean checkout at the published pin. Set `OUT` to a new temporary output directory.

```python
from pathlib import Path
import json
import os
from tools.outside_trial import draft_diagnostics, lay_out

registry = json.loads(Path("tests/outside/projects.json").read_text())
project = next(p for p in registry["projects"] if p["name"] == "breakout")
root = Path(os.environ["OUT"])
source = Path(os.environ["BREAKOUT"])
cases = [("clean", None), ("no-input", None)]
cases.extend((change["name"], change) for change in project["changes"])
for name, change in cases:
    checkout = lay_out(project, source, root / name / "source", change)
    if name == "no-input":
        for folder in (checkout, checkout / "project"):
            path = folder / "routes/pointer-auto.json"
            route = json.loads(path.read_text())
            route["events"] = []
            path.write_text(json.dumps(route))
    for repetition in (1, 2, 3):
        findings, _ = draft_diagnostics(project, checkout, root / name / str(repetition), 300, "diagnostic")
        for finding in findings:
            print(name, repetition, finding["spec"], finding["result"], finding["firstFrame"])
```
