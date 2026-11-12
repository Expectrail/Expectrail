# A probe that asks SAM with a point at the engine's player position (#330)

## What changed
Words did not find the player in the two outside games: 104 images on November 12, and the only
prompt that found anything ("small square") found 38 to 46 squares a frame. Sean chose the way
round it: use the engine's position as the anchor. The Model API takes a point as a prompt; it does
not take a picture of the sprite.

- `agents/sam_observations.py`: `point_prompt` builds the Model API's object prompt for one image
  (`<0f>1<|point;x=..;y=..;w=..;h=..|>`), and `MetaSamClient.segment_at` sends it and gives the box
  under each point's id, or None. It goes through the same sender as every image, so it is counted
  against `EXPECTRAIL_SAM_USD_CAP` and nothing is sent without one.
- `agents/sam_anchor.py`, new: for every Nth frame of a captured run it takes the player's position
  from `trace.json`, places it in the frame with the camera the verifier uses, asks SAM what is
  drawn there, and reports the box, its size in game pixels, how far it reaches above and below
  the origin, the confidence if one is given, whether it holds the point and how much of the frame
  it covers. `--dry-run` prints the points and sends nothing. `--lift N` points N game pixels above
  the origin. A frame where the player is outside the picture is not asked about.
- A probe only. Nothing reads it for a verdict.
- `.github/workflows/outside-sam-probe.yml`: inputs `anchor` and `lift`. The key still never meets
  the outside code: the probe job reads frames and a trace.
- `.github/workflows/sam-probe.yml`, probe mode: inputs `anchor`, `lift` and `sam_usd_cap` (at
  most 2). Since #343 that mode could send nothing, because no workflow but the outside probe set
  a cap. It now has one, for the words as well as the point. The other modes of that workflow are
  not touched and still send nothing.
- `docs/sam.md`: the four word runs with their numbers, and how to ask with a point.

## What was run
- `python3 -m unittest tests.test_sam_anchor`: 33 tests, OK. A scripted transport stands in for
  the service.
- `python3 -m harness.check_seeded --out /tmp/seeded-runs` (Godot 4.7.2), then
  `python3 -m agents.sam_anchor --runs /tmp/seeded-runs/* --every 10 --dry-run`: 95 requests for
  the nine runs. The two fall-through runs are asked about 2 frames each, because the robot has
  fallen out of the picture by frame 20.
- The same runs with a stand-in answer and the overlays drawn: I looked at clean frame 50 and
  sinking_v1 frame 20. The cross is on the robot's lower body in both. So the point is where the
  robot is drawn; what SAM answers there is not known.
- Both workflow steps' shell: `bash -n` passes. Both files parse as YAML with 7 and 13 inputs
  (GitHub's limit is 25).
- **Not run: anything against the service.** No image was sent. Every number about SAM's answer to
  a point comes from the first live run, which Sean starts.
- `python3 -m unittest discover -s tests -t .` on Python 3.13: 2296 tests, OK, 26 skipped.

## Not done
- No verdict uses this. If the live runs show a box of the player's size at the point on clean
  runs and something else on the seeded bugs, the next step is a rule (#330): one object at the
  engine's position, of a size the clean run sets.
- Unknown until the first live run: what comes back when nothing is drawn at the point, whether a
  point's box has a confidence, and what a point request costs. The cap counts it as an image.
- The point is the engine's origin. For the bundled robot that is in its lower legs; `lift` is
  there if SAM answers with a leg and not the robot.
- The outside probe's overlays stay in its artifact, which I cannot fetch; its numbers come back
  as notices. The bundled probe's contact sheets go to the `sam-probe-results` branch as before.
- The month's sum of SAM spend is still not kept anywhere (#267).

## Files
`agents/sam_anchor.py`, `agents/sam_observations.py`, `tests/test_sam_anchor.py`,
`.github/workflows/outside-sam-probe.yml`, `.github/workflows/sam-probe.yml`, `docs/sam.md`
