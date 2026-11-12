# SAM 3.1 in Expectrail

SAM 3.1 turns captured frames into observations: for each object a test spec names, where it is in
each frame and how sure the model is. The evaluator then decides the spec over those boxes with
plain code. This page is the handoff for wiring SAM in for real and calibrating it.

## Status

- Built: the adapter (`agents/sam_observations.py`), the probe (`agents/sam_probe.py`), a manual
  GitHub Actions workflow (**SAM probe**), the verifier wiring, and offline tests
  (`tests/test_sam.py`).
- **Live since October 28.** The probe has run against the real API: about one second per request,
  every response parsed. Findings and the specs they led to are below.
- CI on pull requests keeps using the position-log stand-in (`trace` provider). It has no key.

## What the live probes found (October 28)

Runs 40653267793 to 40656100304 of the SAM probe workflow; per-run results are on the
`sam-probe-results` branch.

- **SAM 3.1 does not see the ground in this game's art.** It segments things, not surfaces.
  "grass-topped ground", "ground", "floor", "dirt", "terrain", "platform", "cliff" and "ledge"
  matched nothing in 13 of 13 frames; "grass" matched the grass band in 3 of 13; "rock" found the
  decorative boulders. So the ground spec (`player-stays-above-ground`) cannot be judged by SAM.
- **"small robot character" also matches the red beetle enemies**, at up to 0.84 confidence. If the
  robot fell out of view, SAM would point at an enemy and the bug would be missed.
- **"blue robot" matches only the robot**: 120 of 120 clean frames (lowest 0.64), nothing else in
  the scene ever matched. "blue and white robot", "robot boy" and "astronaut" were close behind;
  "robot" and "small robot" also match the enemies.
- **"gold coin" finds the coins**: 120 of 120 clean frames (lowest 0.69), 11 to 16 coins a frame.

That led to two specs Sean approved on October 28:

| Spec | Prompt | Clean (every frame) | Seeded bugs (every 4th frame) |
| --- | --- | --- | --- |
| `player-always-visible` | blue robot | pass, 120/120 | fall-through v1, v2: fail (robot seen in 6/31); layering v1, v2: fail (17/31); missing-texture: pass |
| `coins-visible` | gold coin | pass, 120/120 | missing-texture v1, v2: fail (0/13) |

Together they fail all six seeded bugs with no false alarm on the clean run.

### The ground, from the level (October 28)

SAM cannot see the ground, so the harness now records it: each tick, the solid tile surface under
the robot (from the tiles' authored collision polygons, never from the robot's own shape) and the
camera transform from world to frame pixels, and once per run every solid tile polygon of the
level. **The verifier never takes the ground from the candidate's own level**: a candidate may edit
`level/**`, so a "fix" could bury the robot and lower the floor polygons by the same amount (an
independent review did exactly that, `agents/fixtures/fix-and-lower-the-floor.patch`, and it was
accepted). The verifier instead replays the unpatched game for two ticks, reads its level
surfaces, and recomputes every replay's ground line from them. That attack is now rejected on the
candidate and on the held-out routes. The ground spec then has two judges, both in
captured-frame pixels so `tolerancePx` means the same for each:

- **Engine** (always): the robot's feet from the position log (origin plus a constant measured on
  the clean game) against the ground line. Before this, the floor came from the robot's own
  resting height, so a robot resting too low looked fine.
- **Hybrid** (with SAM on): SAM's box for the robot against the same ground line. This one also
  sees a robot that is only *drawn* in the wrong place.

### The drawn floor (October 30)

Both judges measured the robot against the floor's collision, so a floor drawn somewhere its
collision is not would be invisible to every check. This check was added on October 30, after the
first held-out run's one miss.
The harness now also renders the level's tile layers alone, once per run, in a second viewport that
shares the game's 2D world but draws only canvas items on a visibility layer no game node uses (the
tile layers and the nodes above them are given it at run time; the main view draws every layer, so
the captured frames are byte-identical). Per world column it logs where the tiles are opaque
(`levelArt` in trace.json). The ground line is now the higher of the clean level's collision and
the floor as the candidate's game draws it, its top lowered by the grass on the tiles (8 px: over
all 3,648 exposed surface columns of the clean level the art starts 1 to 10 px above the
collision). A floor drawn higher than it collides fails the ground check under every judge, with
SAM on or off; a floor drawn lower leaves the collision in charge.

It was built after the miss, from the public game, without reading sinking/v4's patch, and checked
on the four public routes before it ran on the held-out set (`bench/drawn-floor/`): no development
variant or candidate fixture changes verdict, the clean game's worst gap is 2 px, and two
floor-art bugs written for it (the tiles drawn 26 px higher by a shader, or by the tile set's texture
origin) fail on every route. Art counts as a floor only if it starts at most 64 px above the robot's
origin, as the collision search does, and reaches down past its feet: a platform overhead, and the
overhanging end of a platform the robot jumps up beside, were both taken for the floor on public
routes before that rule.

Known limits: it reads the tile layers only (a floor drawn by some other node is not seen), and a
candidate whose own level script strips the render's visibility layer from its tiles would leave
the ground judged on collision alone, as before.

Live probe (run 40706769342), worst gap between the robot's drawn feet and the ground line:

| Run | Worst gap (frame px) | Hybrid ground check |
| --- | --- | --- |
| clean | +7 (every one of 120 frames checked: never above +7) | pass |
| sinking v1: collision shape 26 px too high | +59 | fail (the engine check fails it too) |
| sinking v2: sprite drawn 26 px too low | +59 | fail (the engine check cannot see it) |
| fall-through v1, v2 | +72, then the robot leaves the screen | fail |

Measured afterwards, never tuned on: held-out fall-through v4 (since retired, see
docs/evaluation.md; a robot that walks buried to the waist) passed the old position-log check and passed gameplay. The engine check with the ground
line now fails it from frame 4.

**End to end with SAM on (October 28, live API, harness replays, private held-out route):**

| Candidate | Without SAM | With SAM |
| --- | --- | --- |
| `fix-collision-mask.patch` (the real fix) | accept | **accept**: all 8 checks pass, held-out route passes every visual spec (run 40698021243) |
| `fix-but-hide-player.patch` (stops the fall, draws the robot behind the scenery) | **accept** | **reject**: player-always-visible fails on the candidate and on the held-out route; ground, gameplay, coins and clean all pass (run 40698743697) |

The second row is the reason vision is in the loop: the position log says the robot is exactly
where it should be, and only the picture shows it can't be seen. To repeat either run: Actions,
**SAM probe**, mode `verify`, and the candidate's path under `agents/fixtures/`.

**Development detection (mode `dev-bench`):** the same jobs, routes and checks for the public
development variants in `bugs/` (ids `dev/<family>/vN`), so the two sets are measured the same way
and reported separately.

First run, October 29 (run 40841977642, recorded in `bench/detection/dev.json`), same five routes
and checks:

| Development variant | Engine | Gameplay | Hybrid | player-always-visible | coins-visible | Caught, SAM on | Caught, SAM off |
| --- | --- | --- | --- | --- | --- | --- | --- |
| clean (control) | 5 pass | 5 pass | 5 pass | 5 pass | 5 pass | no false alarm | no false alarm |
| physics-fall-through/v1 | 5 fail | 5 fail | 5 fail | 5 fail | 5 pass | yes | yes |
| physics-fall-through/v2 | 5 fail | 5 fail | 5 fail | 5 fail | 5 pass | yes | yes |
| sinking/v1 | 5 fail | 5 pass | 5 fail | 2 fail, 3 pass | 5 pass | yes | yes |
| sinking/v2 | 5 pass | 5 pass | 5 fail | 2 fail, 3 pass | 5 pass | yes | no |
| missing-texture/v1 | 5 pass | 5 pass | 5 pass | 5 pass | 5 fail | yes | no |
| missing-texture/v2 | 5 pass | 5 pass | 5 pass | 5 pass | 5 fail | yes | no |
| layering/v1 | 5 pass | 5 pass | 5 needs-review | 5 fail | 5 pass | yes | no |
| layering/v2 | 5 pass | 5 pass | 5 needs-review | 5 fail | 5 pass | yes | no |

With SAM on, 8 of 8 development variants are caught; without it, 3 of 8. Same pattern as the held-out
set: the hybrid is needs-review on layering, and the sinking variants also fail player-always-visible
on some routes (both unexplained so far).

**Held-out detection (mode `heldout-bench`):** for each active held-out variant, and the clean game
as a false-alarm control, the workflow renders the game with the variant and no fix on the smoke
route and every private route, then judges it with the engine ground check, the hybrid ground check,
both SAM specs and the gameplay check (`agents/heldout_bench.py`). A variant counts as caught when a
check fails on at least one route. Each variant gets one annotation with its id, per-check counts
and verdicts; nothing else from the private set leaves the runner (no artifacts, and the harness
output goes to a file that is never printed).

First full run, October 28 (run 40805529944; `bench/detection/held-out.json` now holds the re-run below), five
routes per variant, every pass confirmed on every frame:

| Held-out variant | Engine | Gameplay | Hybrid | player-always-visible | coins-visible | Caught, SAM on | Caught, SAM off |
| --- | --- | --- | --- | --- | --- | --- | --- |
| clean (control) | 5 pass | 5 pass | 5 pass | 5 pass | 5 pass | no false alarm | no false alarm |
| physics-fall-through/v5 | 5 fail | 5 fail | 5 fail | 5 fail | 5 pass | yes | yes |
| physics-fall-through/v6 | 5 fail | 5 fail | 5 fail | 5 fail | 5 pass | yes | yes |
| missing-texture/v5 | 5 pass | 5 pass | 5 pass | 5 pass | 5 fail | yes | no |
| missing-texture/v6 | 5 pass | 5 pass | 5 pass | 5 pass | 5 fail | yes | no |
| layering/v5 | 5 pass | 5 pass | 5 needs-review | 5 fail | 5 pass | yes | no |
| layering/v6 | 5 pass | 5 pass | 5 needs-review | 5 fail | 5 pass | yes | no |
| sinking/v3 | 5 fail | 5 pass | 5 fail | 3 fail, 2 pass | 5 pass | yes | yes |
| sinking/v4 | 5 pass | 5 pass | 5 pass | 5 pass | 5 pass | **no** | no |

With SAM on, 7 of 8 held-out variants were caught; without it, 3 of 8. No false alarm on the clean
routes either way. The miss was sinking/v4.

**Re-run with the drawn floor, October 30** (run 41003749744, commit 92508d9, recorded in
`bench/detection/held-out.json`): every count above is unchanged except sinking/v4, which now fails
the engine and hybrid ground checks on all 5 routes. With SAM on, 8 of 8 held-out variants are
caught; without it, 4 of 8; no false alarm on the clean routes either way. The check that catches it
was built after the miss (see "The drawn floor"), so sinking/v4 is caught by a check made for its
class, not blind; the other seven were caught before that check existed. SAM read 7,693 images
($19.23); each variant took 4 to 8 minutes on a GitHub runner. Muse Glimmer checked against the
engine, with no SAM key, got the same on the same commit: 8 of 8, 4 of 8 without vision, no false
alarm (run 41003751876; docs/open-weights.md).

Not yet explained: the hybrid's needs-review on layering, and sinking/v3 failing
player-always-visible on three routes.

## Where SAM runs

SAM 3.1 is on the Meta Model API, the same service and key type as Muse Spark. No GPU and no
Hugging Face access are needed.

| | |
| --- | --- |
| Endpoint | `POST https://api.meta.ai/v1/responses` |
| Model | `sam-3.1` |
| Key | `MODEL_API_KEY`, from the shell or the gitignored `.env`; never committed, never pasted into chat |
| One request | one concept prompt (a short noun phrase) and one frame as a base64 PNG |
| Asked for | `include_confidence` (the evaluator thresholds on it), masks in the small one-bit encoding |

`MODEL_API_KEY` is not on Muse Code's environment allowlist (`agents.keys.MUSE_ENV_ALLOWLIST`),
and a test keeps it that way. That only protects the variable, not the value: if `MODEL_API_KEY`
and `META_API_KEY` hold the same key, the fixer holds the verifier's key too. **Use a separate
key for SAM** (a second key from dev.meta.ai, stored as the `MODEL_API_KEY` secret and in your
`.env`). The overnight loop and `agents.prove_live` refuse to run Muse Code with SAM on when
`MODEL_API_KEY` is missing or is the same key as `META_API_KEY`; the adapter also warns. The SAM
probe workflow runs no fixer, so it may fall back to `META_API_KEY`.

Check the pricing and rate limits page on dev.meta.ai before a big run. The probe's `--dry-run`
prints how many requests it would send.

## Run it

**Every run needs a spend cap (November 12, 2026).** `EXPECTRAIL_SAM_USD_CAP` is the most one run
may spend on SAM, in US dollars at list price ($2.50 per 1,000 images, $0.20 per 1,000 video
frames). Every try is counted against it before it is sent, a failed try included, so the count can
only be over what is billed. A request that would pass the cap is not sent: the run's checks that
still needed SAM end as needs-review with the reason. The judge ladder ends there: it does not
wait and ask again, and it does not go on to Glimmer, because a stop that holds spend must not
start other spend and an accept must not come from a judge that was asked only because the money
ran out. The candidate stays needs-review for a person. **Without the variable nothing is sent at all.** The limit for the
project is $200 in a calendar month and never more (#327); the cap is what gives every run a worst
case, and the count across the month is the next part of #267. **No workflow in this repository
sets the variable yet, so every live SAM call from a workflow stops with that reason until one
does.** That is on purpose: Sean goes through each live run and its cap first.

**From GitHub, no setup.** Actions, then **SAM probe**, then **Run workflow**. It renders the clean
game and every seeded bug, probes every 10th frame (13 frames a run), and puts `probe.md` in the
run summary. Overlays and contact sheets are in the `sam-probe` artifact. It uses the
`MODEL_API_KEY` secret, or `META_API_KEY` if that is the only one set. The workflow appears in the
Actions list once this file is on `main`.

**Locally:**

```sh
export MODEL_API_KEY=...                      # or put it in .env
export EXPECTRAIL_SAM_USD_CAP=0.50            # the most this run may spend; nothing is sent without it
python3 -m harness.check_seeded --out runs/seeded          # clean + seeded bugs, with frames
python3 -m agents.sam_probe --runs runs/seeded/*/ \
  --spec specs/player-stays-above-ground.json --every 10 --dry-run   # what it would send
python3 -m agents.sam_probe --runs runs/seeded/*/ \
  --spec specs/player-stays-above-ground.json --every 10 --out runs/sam-probe
open runs/sam-probe/probe.md runs/sam-probe/*-sheet.png
```

**One replay, then its verdict:**

```sh
python3 -m agents.sam_observations --run runs/seeded/physics-fall-through_v1 \
  --spec specs/player-stays-above-ground.json
```

**The whole loop:** set `EXPECTRAIL_OBS_PROVIDER=sam`. For the candidate, clean and held-out
replays, the verifier then judges:

- the ground spec on the engine's position log, as before;
- every spec in `agents.verifier.SAM_SPECS` (player always visible, coins visible) on SAM's view of
  the same frames. Override the list with `EXPECTRAIL_SAM_SPECS=specs/a.json,specs/b.json`.

Every check must pass. The suite provenance says which source judged what. The held-out routes were
probed with SAM on October 28: run 40698021243 on the one route the set had then, and runs 40714948968
to 40714993165 on all four. Their frames never left the runner; only the per-spec verdicts did.

**Prompt sweeps.** `--sweep player="blue robot|robot boy|astronaut"` tries several prompts for one
object over the same frames; `--set ground=grass` probes one other prompt without editing the spec.
Both are inputs on the SAM probe workflow, together with `runs` to probe only some runs.

## Asking with a point at the engine's player position (November 12)

**Words did not find the player in a game the team did not write.** Four runs of the outside SAM
probe on November 12, 13 frames each and one image a prompt, 104 images in all:

| Run | Project | Prompt | Frames with a match | Matches a frame |
| --- | --- | --- | --- | --- |
| [43292219671](https://github.com/Expectrail/Expectrail/actions/runs/43292219671) | kinematic-character | player character | 0 of 13 | 0 |
| [43293706871](https://github.com/Expectrail/Expectrail/actions/runs/43293706871) | kinematic-character | small square | 13 of 13, median score 0.84 | 38 to 46 |
| the same | kinematic-character | grey square | 0 of 13 | 0 |
| the same | kinematic-character | small grey square | 0 of 13 | 0 |
| [43294012542](https://github.com/Expectrail/Expectrail/actions/runs/43294012542) | dodge-the-creeps | player character | 0 of 13 | 0 |
| [43294995368](https://github.com/Expectrail/Expectrail/actions/runs/43294995368) | dodge-the-creeps | grey monster | 0 of 13 | 0 |
| the same | dodge-the-creeps | round grey creature | 0 of 13 | 0 |
| the same | dodge-the-creeps | one-eyed creature | 0 of 13 | 0 |

The kinematic demo's player is a grey square in a level made of squares: the one prompt that found
anything found every square. The frames of these runs were not looked at by anyone, so a blank
capture of Dodge the Creeps is not ruled out.

**A point asks a different question.** The Model API takes a point as a prompt ("what is the
object drawn at this pixel") in place of words; the two cannot be mixed in one request, and there
is no way to give it a picture of the sprite
([the API's page](https://dev.meta.ai/docs/sam/segmenting), read November 12). The engine's
position log says where the player is, the camera it logs places that in the frame, and
`agents/sam_anchor.py` asks SAM about that pixel:

```sh
export EXPECTRAIL_SAM_USD_CAP=0.50
python3 -m agents.sam_anchor --runs runs/seeded/* --every 10 --out runs/sam-anchor --dry-run   # the points, nothing sent
python3 -m agents.sam_anchor --runs runs/seeded/* --every 10 --out runs/sam-anchor
```

For each probed frame it reports the box that came back, its size in the game's own pixels, how
far it reaches above and below the player's origin, its confidence when one is given, whether it
holds the point, and how much of the frame it covers. It is a probe: it decides nothing and no
verdict reads it. From GitHub: **Outside SAM probe** with `anchor` ticked for an outside project,
**SAM probe** in probe mode with `anchor` ticked for the bundled game and its seeded bugs. Both
take `sam_usd_cap`, at most 2. One image a frame: 13 a run at most, 95 for the bundled game's nine
runs ($0.24 at the list price of an image), because the fall-through runs leave the picture.

### What the first live runs showed (November 12)

Five runs, 308 images, $0.77 counted at the list price of an image. Every answer came with a
confidence. The second bundled run repeated the first by accident (the `lift` field was left at
0): all 95 of its answers are the same as the first run's, to the pixel and to the last digit of
the confidence.

**The two outside games, clean, point at the origin.**

| Run | Project | Asked | Box holds the point | Box (game px) | Confidence |
| --- | --- | --- | --- | --- | --- |
| [43304967915](https://github.com/Expectrail/Expectrail/actions/runs/43304967915) | kinematic-character | 13 of 13 | 13 | 16 x 16 or 16 x 17 in every frame (the sprite is 16 x 16) | 0.91 to 0.95 |
| [43305243223](https://github.com/Expectrail/Expectrail/actions/runs/43305243223) | dodge-the-creeps | 10 of 13 | 10 | 30 or 31 wide, 31 or 32 tall in 9 frames | 0.73 to 0.92 in those 9 |

- In Dodge the Creeps' frame 0 the game has not started and its player is hidden. SAM answered
  with a box over the whole frame (480 x 720) at confidence 0.012. That is what "nothing is drawn
  here" looked like, once.
- Three Dodge frames were not asked about: the game holds its player at x = 480, the picture's
  width, and the probe called a point on the edge "outside". Fixed since: the last pixel inside is
  asked.
- So the Dodge capture is not blank, which the word runs could not show.

**The bundled game and its eight seeded bugs**, published on the `sam-probe-results` branch
(`anchor.json`, `anchor.md` and a contact sheet a run): runs
[43306507436](https://github.com/Expectrail/Expectrail/actions/runs/43306507436) and 43308321074 with
the point at the origin, which is in the robot's lower legs, and
[43310237299](https://github.com/Expectrail/Expectrail/actions/runs/43310237299) with the point
14 game pixels higher, at mid-body. "Outside the clean range" below means the box's width, height,
or its reach above or below the point is outside the smallest and largest value of the clean run's
own 13 frames **in the same run**.

| Run | What the bug is | Frames outside the clean range, point at the origin | The same, 14 px higher | Confidence under 0.8, 14 px higher |
| --- | --- | --- | --- | --- |
| clean | none | 0 of 13 | 0 of 13 | 3 of 13 (0.50, 0.72, 0.75) |
| missing-texture v1, v2 | the coins' texture is missing | 2 of 13 | 0 of 13 | 2 of 13 |
| layering v1, v2 | the robot is drawn behind the level | 6 of 13 | 9 of 13 | 7 of 13 |
| sinking v1 | the robot stands lower, and the engine says so | 5 of 13 | 4 of 13 | 3 of 13 |
| sinking v2 | the robot is drawn 26 px lower than the engine says | 13 of 13 | 13 of 13 | 7 of 13 |
| physics-fall-through v1, v2 | the robot falls out of the picture | 2 of 2 asked | 1 of 2 asked | 0 of 2 |

What that says:

- **At the origin the clean run itself is unsteady.** In 2 of 13 clean frames SAM answered with a
  small part of the robot (19 x 24.5 and 12.5 x 7.5 game px, confidence 0.28 and 0.48), so the clean
  range there is 7.5 to 63.5 px tall and means little. Frame 0 of clean and of sinking v1 have the
  point at the same pixel; one got the whole robot and the other a 7 px part.
- **At mid-body every clean frame is the robot:** 30.5 to 59 px wide, 52 to 64.5 px tall.
- **Sinking v2 is outside the clean range in every frame at both points.** Its trace is the same as
  the clean game's, so the engine's record cannot see it. 14 px higher, its box reaches 50.5 to
  68.5 px below the point; the clean run's reaches 25.5 to 37.5.
- **Layering shows in 9 of 13 frames** at mid-body: slivers 16.5 to 46 px tall where the robot is
  behind the ground, and a box 140 to 154 px wide around a tree it is behind (seen on the contact
  sheet). In 4 frames where it is in the air it is inside the clean range.
- **Missing texture looks clean, as it should from here:** the texture is the coins'. A point on
  each coin would be the test for it; that was not run.
- **Sinking v1 and fall-through are the engine's to catch.** The robot and the engine's position
  move together, so a box measured from the point looks much the same.
- **Confidence does not separate anything frame by frame.** The clean run dips to 0.50, and sinking
  v2 scores up to 0.92.

What it does not say:

- The clean range was set on the same 13 frames it is then held against. No clean route it was not
  set on has been asked about, so nothing here is a false-alarm rate.
- 13 frames a run, one route, one game with broken copies. No outside game has a broken copy.
- 14 is this robot's number. The two outside games worked at 0 because their origin is the middle
  of the sprite. The general form is a point at the middle of the player's collision body, which
  the harness does not log yet.
- What a point request is billed at is still not known; the counts above price it as an image.

### The rule those numbers point to (agreed November 12, not in any verdict)

Sean agreed the rule to try: **one box holding the point, its size and its reach above and below
the point inside the range a clean run sets.** Confidence is not part of it. `agents/anchor_rule.py`
is that rule as arithmetic over an `anchor.json`:

```sh
python3 -m agents.anchor_rule --calibrate runs/sam-probe/anchor.json:clean \
    --judge runs/sam-probe/anchor.json --out runs/sam-probe
```

- **Set:** from a clean run, the smallest and largest width, height, reach above and reach below of
  its boxes in game pixels, each widened by a pad (2 px unless told otherwise). A clean run with a
  frame the observer could not read sets no range.
- **Judge:** a frame is out when its box does not hold the point or a measure is outside its range.
  A run fails on its first frame out. A frame that was asked and got no box is never a pass
  (needs-review), and a run with no frame judged is needs-review.
- **Why a pad:** the clean run and the missing-texture run show the same robot in the same frames,
  only the coins differ, and between them a box's height and reach moved by up to 1.5 px (its width
  by 5 px, once). With no pad, the clean run has one frame outside the range the missing-texture
  run sets. 2 px is a starting value, not a tuned one.

On the recorded answers with the point at mid-body (`tests/data/sam-anchor/bundled-lift-14.json`),
set on the clean run, pad 2:

| Run | Result | Frames out of those judged |
| --- | --- | --- |
| clean | pass (it set the range) | 0 of 13 |
| missing-texture v1, v2 | pass | 0 of 13 |
| layering v1, v2 | fail | 9 of 13 |
| sinking v2 | fail, by its reach in every frame | 13 of 13 |
| sinking v1 | fail, on one frame whose box is 73.5 px wide | 1 of 13 |
| physics-fall-through v1, v2 | pass on the 2 frames before the robot leaves the picture | 0 of 2 |

Sinking v2's first frame reads "above 3, below 56" against the clean frame's 29 and 30: the patch
moves the drawing 26 px down, and that is the 26.

**None of this is a false-alarm rate.** The range was set on the smoke route's clean run and the
only clean-looking runs it was held against are that run and the missing-texture runs, the same
frames. The measurement that matters is the clean game on routes the range was not set on. The
SAM probe workflow can now make it: probe mode with `anchor` ticked, `lift` 14, and `clean_routes`
set to `coins,combat,traversal` replays the clean game on those routes as `clean-coins` and so on,
asks about all twelve runs (131 images, $0.33) and puts the rule's table in the summary and on the
`sam-probe-results` branch. A clean route that fails there is a false alarm, and the rule changes
before it goes anywhere near a verdict.

What it leans on: the point is the engine's. A game that lies about where its player is sends the
question to the wrong place, so this can never be the only evidence that a player is where the
engine says. It can say what is drawn there: nothing, something of the player's size, or the level.

## What is still open

1. **Held-out routes under SAM.** Run the verifier with `EXPECTRAIL_OBS_PROVIDER=sam` on the
   verifier machine and read `verdict-held-out.json`: each route lists `visuals` per spec. Coins
   in particular may be off screen on some private route.
2. **Ground spec tolerance: decided.** Clean never goes above +7 frame px and the sinking bugs sit
   at +47 or more; Sean approved 20 px on October 28, with the player prompt "blue robot".
3. **Score margin.** The lowest clean scores were 0.64 (player) and 0.69 (coins) against the 0.5
   threshold. Watch it when the art or the camera changes.
4. **Cost of confirming.** A passing replay now costs 120 requests per spec instead of 31; the
   clean replay is identical across attempts, so after the first night it comes from the cache.

## Video input: measured, not used (October 29)

sam-3.1 also takes a whole run as one video, at $0.20 per 1,000 frames instead of $2.50 per
1,000 images. That is about $0.05 for both prompts over a 120-frame run, against up to $0.60.
`agents/sam_video.py` sent every frame of the clean game and the 8 public bugs (smoke route
only) both ways. Results are in `bench/sam-video/`. The module does not time itself; the wall
clock is the Actions job record — the sam-video job took 4 min 37 s for the clean run
(40972278900) and 11 min 27 s for the eight bugs (40972947066), rendering plus both send paths.

- **Coins:** the same verdict and the same per-frame verdicts on all 9 runs.
- **The robot:** video tracks it from frame to frame and carries it through what hides it.
  - Sinking v1 and v2: as the robot sinks, images lose it on 11 frames, so `player-always-visible` fails. Video reports it on every frame, so that spec passes.
  - Sinking, frames where both modes see the robot: video puts its feet up to 15 px higher. The ground check's tolerance is 20 px.
  - Layering v1 and v2: on frames 100 to 119 the robot is entirely behind a tree. Images find nothing. On frame 110, video reports a "blue robot" at the foot of the tree, where no robot is visible. The verdict still fails, but on 33 frames instead of 49.
- **Confidence:** video gives one score per tracked object, not per frame: 0.938 for the robot on every clean frame. The score floor means nothing in video mode.

So the verifier keeps one image per frame. Occlusion and sinking are two of our four bug
families, and they are exactly where video errs, toward a pass. Video is a candidate only for
coins, and only after testing coins that blink or vanish for a few frames. No public variant
does that yet.

## How it looks at fewer frames

- **Sample.** Every Nth frame of the spec's window, plus its last frame (`EXPECTRAIL_SAM_EVERY`,
  default 4).
- **Refine.** When the spec fails on a sampled frame, look at every frame between the last sample
  that passed on its own and the first failing one, so the first bad frame in the report is exact.
  A sample where the object was missing or the check did not apply does not count as passing, so
  the stretch reaches back past it. In the offline test, a fall that starts between samples is
  found at the same frame as looking at every frame, from 22 of 120 frames.
- **Confirm.** A pass on the sample is never the last word: before passing, SAM looks at every
  remaining frame of the window, so a pass, and any accept built on it, rests on every frame. A
  fail found on the sample stays cheap. `EXPECTRAIL_SAM_CONFIRM=0` turns this off, for probing only.
- **Cache.** Results are kept by frame SHA-256, prompt, model and request settings, so a frame
  that was already judged is never sent again. Replays are bit-identical, so an unchanged route
  costs nothing the second time.
- **Shared within a CI run.** A correct fix renders the clean game's frames byte for byte (the real
  fall-through fix: 120 of 120 smoke-route frames), and every verification judges the clean game as
  its control, yet each CI job starts with an empty cache: a correct fix's verification cost 1,164
  images, exactly what the clean game costs on the same five routes (run 41003749744). In the fix
  matrix workflow (`sam_cache`, default `shared`), one job judges the clean game on the smoke and
  private routes (`agents/sam_warm.py`) and, only if every check passes with the clean replay's
  score floor, shares SAM's answers with the run's other jobs, encrypted with `HELDOUT_TOKEN` since
  they cover the private routes, for one day. A weak or missing answer is never shared: SAM's
  answers vary slightly between requests, and a shared one would repeat in every job. A job
  restores the answers outside the fixer's sandbox, still sends every frame whose bytes differ,
  and judges everything itself if the restore fails. `public` shares the smoke route only; `off` is
  the old behaviour.
- **No private routes after a fail.** Any failed check rejects, so a candidate that has already
  failed is not replayed on the private routes: four renders and SAM's look at every frame of them
  could not change the decision. The probes' verify mode sets `EXPECTRAIL_HELDOUT_AFTER_FAIL=run`,
  so it still reports every private route for a fake fix.
- **Counting assertions are not sampled.** `visible` with a `minFraction` below 1 looks at every
  frame. `reaches` samples, and unless a sample already reaches the goal it looks at every frame
  before deciding.

What sampling still saves: rejects. A candidate that fails is caught on the sample and its first
failing frame is pinned down; the remaining frames are never sent. What it no longer risks: a
glitch between samples slipping through a pass. In the offline test, a robot that dips into the
ground for three frames between samples passes on the sample and fails, at the exact frame, once
confirmed. Every verdict says how many frames it judged, and the observations document records
`framesAnalyzed`, `refined` and `confirmed` against `framesCaptured`.

**The cache is verifier state.** It lives outside the repo (`~/.cache/expectrail/sam`, or
`EXPECTRAIL_SAM_CACHE`), so it is never in the fixer's worktree, and under bubblewrap the fixer gets
an empty home directory and cannot reach it. With no OS sandbox nothing stops a process on the same
machine from writing there, so set `EXPECTRAIL_SAM_CACHE=off` for the recorded demo and any run
whose verdict has to be beyond question. The run's shared answers come from that run's own warm
job, are written to the cache before Muse Code starts, and are SAM's answers for the clean game's
frames; `sam_cache: off` turns sharing off for a run.

## When SAM fails

Any failure makes the check needs-review, never a pass and never a crash. That covers a failed,
partial or unrecognised reply, a box without a confidence, a number that is not finite, missing
frames, and anything unexpected. With SAM on in the verifier, each SAM spec is its own check:

- candidate and clean replays: that spec's check is needs-review, with the error in
  `observations-<spec>-error.txt` or `observations-clean-<spec>-error.txt`; the ground check is
  still judged on the engine's position log;
- held-out routes: the route is needs-review for that spec (see `visuals` in
  `verdict-held-out.json`);
- no frames to look at (offline fixtures, a failed clean harness run, the interim held-out fixture
  or no private set mounted): the SAM checks are needs-review, so a SAM-on accept always means SAM
  looked at the candidate, the clean game and every private route.

Rate limits, server errors and dropped connections are retried three times with backoff; bad
requests are not retried. After the first failure, queued requests for that replay are cancelled.
The parser is strict: text it does not recognise is an error, not "nothing found", so a refusal or
a format change can never be cached as a frame with no player in it.

## Not built yet

- **Video mode.** SAM 3.1 can take a whole clip in one request and track objects with stable ids
  (billed per frame, 50-frame minimum per request, up to 16 tracked objects). Worth it if
  per-frame requests are slow or costly. Trade-offs: H.264 compression of the frames, and the
  cache would work per run instead of per frame.
- **Box and point prompts from the engine.** SAM 3.1 also takes a box or point saying where to look.
  Prompting it with where the engine says the player is would make detection more reliable, and a
  missing texture or a hidden sprite would still come back empty. It also makes vision less
  independent of the engine, so if we use it we say so.
- **Masks.** Boxes are all the evaluator uses today.
