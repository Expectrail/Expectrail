# Judging the Unity game

Expectrail judges the Unity game, Platformio (`game/unity-platformer`), the way it judges the Godot
game: approved test specs, read by the unchanged evaluator (`expectrail/evaluator.py`), on what the
engine records and, in step 3 of P7, on what SAM 3.1 sees in the frames. This page holds the
measurements those checks rest on. Every number comes from a recorded run, with the command that
reruns it.

## Engine observations

`agents/unity_observations.py` turns a Unity trace (`harness/unity/`, see
[harness.md](harness.md#unity-harness)) into observations:

- **player, coin, enemy, projectile:** each object's renderer bounds in frame pixels, only where the
  harness found it visible (active, renderer on, sprite drawn and not transparent, inside the
  camera's view);
- **ground:** the level's ground line under the player, from the ground tilemap's cells, placed with
  the camera of the frame.

None of the constants measured on the Godot game (`agents/observations.py`: the robot's feet 13.25 px
below its origin, its 60 px height, the coin's size, the 64 px ground search) is used. An object the
harness did not find visible is absent from that frame: a `visible` spec fails there, and a
`never-crosses` spec is needs-review there, never a pass.

## Calibration on the clean game

Measured on the clean game's smoke route (`harness/routes/unity-smoke.json`, 200 ticks) by the replay
job of the Unity workflow, which prints:

```sh
python3 -m agents.unity_observations calibrate runs/unity/replay/run-00/trace.json
```

Runs 17 (42754753371, EPYC 9V74) and 18 (42758198963, EPYC 7763) gave the same numbers, as they must:
the trace is the same on every runner (`8079801f135d`). Frame pixels, 1600 x 960.

| Measure | Rows | Min | Median | Max |
| --- | --- | --- | --- | --- |
| Player visible | 200 of 200 | | | |
| Player box width | 200 | 68.57 | 73.39 | 80.0 |
| Player box height | 200 | 137.14 | 146.79 | 160.0 |
| Box bottom minus ground line, on the floor, on the ground tilemap (+ is below) | 132 | -1.25 | -1.13 | -0.98 |
| The same, on the floor but standing on something else | 6 (ticks 34-35, 94-95, 137-138) | -561.21 | | |
| The same, in the air | 62 | -559.95 | -359.92 | -2.99 |
| Coins visible a frame | 200 | 1 | 1 | 2 |
| Coin box width and height | 213 | 87.77 | 92.96 | 102.4 |

The box sizes vary because the camera zooms during the route.

## The specs, as drafted

In `specs/unity/`. Each carries a person's approval (commit `2b2785a`); only a person approves a
spec, with `python3 -m expectrail.spec_writer approve specs/unity/<id>.json --by "<name>"`. The Godot loaders
read `specs/*.json` only, so these are not judged on the Godot game.

- **`unity-player-stays-above-ground`**: `never-crosses`, the player's box bottom against the ground
  line, `tolerancePx` 4. On the clean route the bottom is never closer than 0.98 px above the line,
  so the clean game passes with a 4.98 px margin, and a sink of more than 4 frame px (about 7 world
  px, a twentieth of a 128 px tile) fails. On the 6 floor rows standing off the ground tilemap the
  line is far below the player, so a sink there is not seen; they are 6 of 200 rows. The tolerance
  is the engine's; SAM's boxes are coarser, and step 3 may need a wider one for SAM.
- **`unity-player-always-visible`**: `visible`, the player in every frame of 0 to 199. Visible in
  200 of 200 on the clean route.
- **`unity-coins-visible`**: `visible`, at least one coin in every frame of 0 to 199. One or two in
  every frame on the clean route; a route that collects every coin in view would fail it, so it
  belongs to routes like this one.

The windows cover the whole smoke route, 200 frames.

**Prompts.** The prompts are for SAM in step 3. "green cartoon alien": the player prefab's default
animator is the green alien's, and the colour is otherwise a menu choice the harness does not make;
no one has yet checked it against a frame. "coin": the level has bronze, silver and gold coins.
Step 3 checks both against clean frames before any score is set.

**SAM will not judge the ground.** SAM 3.1 does not see the ground in the Godot game's art: it
segments objects, not surfaces, and no ground prompt found anything ([sam.md](sam.md)). A SAM probe
on Nov 10 (run 42867454782) again found the player in 13 of 13 frames and the ground in 0 of 13.
So on Unity, as on Godot, the ground line comes from the engine, never from SAM: with SAM on, the
ground spec puts SAM's player box against the engine's ground line (`engine_objects` in
`agents/unity_observations.py`). The ground spec keeps "grass-topped ground" only because the schema
needs a prompt for every object.

## Not yet done

- Wiring the clean level's ground into the verdict. `agents.unity_observations.with_reference_ground`
  recomputes every row's ground from the clean game's level surfaces with the harness's own search
  (its constants from the map), as the Godot verifier does (`agents.observations.with_reference_ground`),
  because a candidate could otherwise move the ground to pass ([sam.md](sam.md), "The ground, from
  the level"); SAM cannot check the ground, so on Unity this is the ground spec's only guard. The replay
  job reports whether it reproduces the harness's ground on every row of the clean trace. The Unity
  domain in `agents/domain_verifier.py` (below) is what will apply it to a candidate.
- The gameplay check (`agents/gameplay.py` `check_motion`, P7 step 4) and the Unity domain in
  `agents/domain_verifier.py`.
- SAM scored against the engine record on clean frames (P7 step 3).
