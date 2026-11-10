# Open weights in Expectrail

**Muse Glimmer 30B can judge every vision check with no hosted vision model, checked against the
game engine; Muse Spark Open writes the checks.** Both are Meta open-weight models, served through
partner inference (Fireworks, Baseten) or our own server. With `glimmer-engine`, the real fix is
accepted and the hide-the-robot fix rejected, on the four private held-out routes too, and the
held-out bench catches 8 of 8 private bug variants with no false alarm and no stray check failure,
as SAM does (8 of 8 on the public development set, also as SAM does), with no SAM key in any of
these runs (Oct 29 to 30). Four of the eight held-out variants are caught only by Glimmer's checks.
The eighth, sinking/v4, is caught by the engine's ground check, not by Glimmer, and that check was
built after the first benches missed it (see the bench below). With `both`, Glimmer is a second pair
of eyes next to SAM 3.1. Muse Spark Open ran live on Baseten on Oct 30 (see "Muse Spark Open, live"
below): valid drafts of our three checks, the ground draft matching the approved spec on all 9 seeded
runs after a prompt fix, and the scripted playtest sorted as the rules sort it. Muse Code (the fixer)
and Muse Voice Transcribe stay on Meta's hosted API.

This page is for anyone verifying the open-weights path, and for us: what runs
on which model, where, and how to check it.

| Role | Model (license) | Served by | Turn it on | Code |
| --- | --- | --- | --- | --- |
| Vision checks: is the robot visible, are the coins drawn, where are the robot's feet against the level's ground line | Muse Glimmer 30B (Apache 2.0, per its model card), together with SAM 3.1 (`both`) or checked against the game engine with no SAM (`glimmer-engine`) | A Fireworks on-demand deployment of `accounts/fireworks/models/muse-glimmer-30b` (Glimmer left Fireworks serverless on Sep 25, 2026); or any OpenAI-compatible server we run | `EXPECTRAIL_OBS_PROVIDER=sam EXPECTRAIL_VISION_BACKEND=both` (keys in `FIREWORKS_API_KEY` and `MODEL_API_KEY`) or `=glimmer-engine` (`FIREWORKS_API_KEY` only) | `agents/glimmer_client.py`, `agents/engine_check.py` |
| Test-spec drafting from plain English | Muse Spark Open (Muse Model License) | Baseten, `meta-models/muse-spark-open` (the id the key lists, Oct 30; an earlier guide named `meta-models/muse-spark-open-1026`, which Baseten does not list) | `python3 -m expectrail.spec_writer draft "..." --endpoint open`, key in `BASETEN_API_KEY` | `expectrail/spec_writer.py` |
| Sorting playtester feedback and drafting checks from it | Muse Spark Open | Baseten | `python3 -m agents.feedback ... --sorter open` | `agents/feedback.py` |
| Measuring both live on public material: the approved checks drafted again, the ground draft judged on the seeded bugs, the scripted playtest sorted | Muse Spark Open, next to Muse Spark on Meta's API | Baseten | Actions, **Spark Open** (`BASETEN_API_KEY`; `META_API_KEY` for the comparison), then `python3 -m agents.spark_open collect --run <id>` | `agents/spark_open.py`, `bench/spark-open/<run>/` |

## Serve Glimmer on Fireworks (on-demand)

Fireworks retired Glimmer from serverless on Sep 25, 2026 (its model page says so), so a request to
`accounts/fireworks/models/muse-glimmer-30b` returns HTTP 404 "Model not found, inaccessible, and/or
not deployed". It still runs as an on-demand deployment: dedicated GPUs, billed per GPU-second while
a replica is up, and able to scale to zero when idle.

1. Create the deployment, from the model's page in the Fireworks dashboard or with `firectl`:

   ```sh
   firectl deployment create accounts/fireworks/models/muse-glimmer-30b \
     --deployment-shape default --min-replica-count 0 --max-replica-count 1 \
     --scale-to-zero-window 15m --wait
   ```

   It prints `accounts/<account>/deployments/<id>`.
2. Put that string in the repository variable `GLIMMER_MODEL` (Settings → Secrets and variables →
   Actions → Variables), or in `EXPECTRAIL_GLIMMER_MODEL` for local runs.
3. The probe workflow wakes the deployment first (`python -m agents.glimmer_client --warm`): a
   deployment at zero replicas answers 503 for a few minutes while it starts, and after a long idle
   it has answered 404 "not deployed" instead, while Fireworks' API reported it ready (7 of 9 bench
   jobs stopped on that in run 40986446779). The wake step waits through both for a deployment id.
4. With minimum replicas at 0 and a 15-minute scale-to-zero window, it stops billing 15 minutes
   after the last request (Fireworks' default window is an hour). Fireworks deletes a deployment
   that has had no traffic for 7 days. Check the GPU price for the shape it picks before leaving it up, and
   recreate it for the judging window (Nov 4 to 9) if the partner needs to see it run.

### If the account is suspended

Fireworks suspends the account when its prepaid credits run out (twice on Oct 29: auto-reload did
not fire). Requests then fail with HTTP 412 mid-run, and the deployment comes back with its replicas
at 0-0 and its scale-to-zero window at 60 minutes, with Re-enable greyed out on the dashboard. After
adding credits, nothing else is needed: the Glimmer workflow's first step,
`python -m agents.fireworks_deployment --restore`, reads the deployment through Fireworks' API and
puts back min 0, max 1 and a 15-minute scale-to-zero window (only those fields), then reads it back
to confirm. Without `--restore` it only reports. By hand: Edit Deployment, Deployment Scaling, Max
Replicas 1, Advanced Options, Scale to Zero Window 15 min, Save.

Each full verify run keeps one H200 up for about 35 to 40 minutes plus the 15-minute tail, about $7
at $8 an hour; a probe about $1 to $3; the held-out bench (9 jobs, 3 at a time, sharing one replica)
about 2 hours 35 minutes plus the tail, about $22 (run 41003751876, Oct 30; an earlier bench split
over two runs took about 1 hour 40 minutes). Keep at least $15 of credit before starting runs, $30
before a bench.

## How Glimmer fits

The verifier asks one question per frame and object: where is "blue robot" (or "gold coin") drawn?
SAM 3.1 answers through the Meta Model API. Glimmer gets the same question, as an image plus a
JSON-only instruction, and answers with boxes in pixels of the frame.

**With `EXPECTRAIL_VISION_BACKEND=both` (the verdict setting), an object counts as found only on
frames where both models find it.** The boxes used for geometry are SAM's. So adding Glimmer can
only make a check stricter than SAM alone: a robot Glimmer cannot see fails, even if SAM finds it.

**Glimmer never decides an accept unchecked.** It reads images the way a language model reads
text, and the fixer controls the candidate's pixels: a fix could draw text into the game that talks
a vision-language model into "the robot is there". So each of Glimmer's answers is checked by
something that cannot be talked to:

- **`both`:** SAM 3.1, a segmenter, must find the object too.
- **`glimmer-engine` (no SAM):** the game engine must have put the object there. The harness logs
  where the robot is and where every coin is on every frame (`player` and `coins` in trace.json,
  projected to frame pixels with that frame's camera). A Glimmer box counts only if it overlaps the
  box of an object the engine placed on that frame and is at most 3x its width and height
  (`agents/engine_check.py`). A box beside the robot, or one over half the screen, is dropped and
  counted in the observations document (`model.engineCheck`). The trace and the check run on the
  verifier's side, after the frame cache; a replay whose trace cannot place objects is needs-review.
  The ground check is judged on the position log under `glimmer-engine` (see "What was measured"):
  Glimmer's boxes are too loose for its 20-pixel tolerance.

The verifier refuses `EXPECTRAIL_VISION_BACKEND=glimmer` with neither check (every vision check
becomes needs-review) unless `EXPECTRAIL_GLIMMER_ALONE=1` is set to measure Glimmer on known
fixtures.

What the engine check does not stop: Glimmer steered onto the object's true position. The fixer can
compute where the hidden robot is, because it wrote the game, and could try to draw text that makes
Glimmer answer with exactly that box. That is a far narrower attack than "write 'robot here'
anywhere", but it is not zero. Where SAM is available, `both` remains the stronger setting.

Everything around the question is shared code (`agents/sam_observations.py`):

- sampling every fourth frame by default (`EXPECTRAIL_SAM_EVERY`; the probe workflow defaults to
  every tenth);
- refining to the exact first bad frame;
- confirming every remaining frame before a pass;
- the cache, keyed by model, endpoint and prompt version;
- turning any failure into needs-review, never a pass.

The evaluator then decides each spec from the boxes, in plain code. Glimmer is never asked "is it
below the ground", only "where is it".

Why open weights matter here: an unreleased game build is confidential, and a
studio wants its quality gate on infrastructure it controls. With `glimmer-engine`, every vision
check runs on Glimmer (the ground check on the engine's position log, as above), which a studio
could serve on its own hardware, and nothing leaves for a hosted vision API. We have run Glimmer only
on a Fireworks deployment; self-hosting is documented from its model card, not tested.

## How to verify it

- Every observations document records `model.name` (the model id) and `model.provider`, for example
  `open-weights glimmer at api.fireworks.ai, self-reported confidence`. The verifier keeps one per
  check in `runs/<run>/verify/`.
- **Glimmer probe** (Actions, manual): mode `probe` renders the clean game and every seeded bug and
  asks Glimmer what it sees (with judge `glimmer-engine`, how many of its boxes agree with the engine,
  and how its coordinates fit the engine's). Mode `verify` runs the Gate 1 path with judge `both`,
  `glimmer-engine` or Glimmer alone (measurement only), including the private held-out routes. Results are posted as
  annotations on the run. The key is only sent over https to `api.fireworks.ai` or the host in the
  `GLIMMER_ALLOWED_HOST` repository variable.
- Self-hosting: Glimmer's model card documents OpenAI-compatible serving with vLLM and SGLang, and
  says the 4-bit weights fit a 24 GB GPU. Point `EXPECTRAIL_GLIMMER_API_BASE` at the server's `/v1`
  URL and set `EXPECTRAIL_GLIMMER_MODEL` to the id it serves. If the server resizes images before the
  model sees them, Glimmer's pixels are in the resized image's space: run the probe and set
  `EXPECTRAIL_GLIMMER_COORDS` to match before trusting any box.

## What was measured (Oct 29, Fireworks on-demand deployment, 1x H200)

Glimmer alone, probe mode, every 10th frame (13 frames a run), on the same seeded runs SAM was
measured on (docs/sam.md, SAM every 4th frame):

| Spec | Clean | Seeded bugs | SAM on the same bugs |
| --- | --- | --- | --- |
| `player-always-visible` (blue robot) | pass, 13/13 (lowest 0.85) | fall-through v1, v2: fail (3/13); layering v1, v2: fail (7/13); sinking v1: fail (12/13); missing-texture v1, v2: pass | fall-through 6/31, layering 17/31, missing-texture pass |
| `coins-visible` (gold coin) | pass, 13/13, 10 to 14 coins a frame | missing-texture v1, v2: fail (0/13); every robot bug: pass | 11 to 16 coins a frame; missing-texture 0/13 |

Runs 40904213270 (robot) and 40915470775 (coins). Glimmer misses the robot in about the same share
of frames as SAM on each bug, and raised no false alarm on the clean run. These runs read its boxes
as pixels, which was wrong (see "Coordinates" below); under `both` only whether Glimmer saw the
object counted, not where, so the verdicts above stand.

Verify mode, judge `both`, every 4th frame, with the four private held-out routes:

| Candidate | Decision | Checks |
| --- | --- | --- |
| `fix-collision-mask.patch` (the real fix) | **accept** | all 8 checks pass; ground, robot and coins pass on 4/4 held-out routes (run 40924660911) |
| `fix-collision-mask.patch`, earlier run | needs-review | as above, except coins on one held-out route had no verdict (run 40915475383) |
| `fix-but-hide-player.patch` | **reject** | player-always-visible fails on the candidate and passes on 0/4 held-out routes; coins pass (run 40915479861) |

The earlier needs-review was an observations error on one held-out route (Glimmer seeing no coins
would have been a fail), in a run that shared the one replica with two others. It did not recur
when the run had the deployment to itself, so its kind is unknown; the workflow now reports the
kind of any held-out error (kind only, see "Glimmer verify held-out error"). An error never
passes a check: it stops at needs-review, so the cost of one is a re-run, not a wrong accept.

Verify mode, judge `glimmer-engine` (Glimmer checked against the engine; the SAM key is not passed
to the run), every 4th frame, every pass confirmed on every frame, with the four private held-out
routes:

| Candidate | Decision | Checks |
| --- | --- | --- |
| `fix-collision-mask.patch` (the real fix) | **accept** | all 8 checks pass; ground, robot and coins pass on 4/4 held-out routes (run 40948206799) |
| `fix-but-hide-player.patch` | **reject** | player-always-visible fails on the candidate and passes on 0/4 held-out routes; ground, coins and gameplay pass (run 40948223160) |

The engine check kept every robot box on the real fix (120 on the candidate, 480 on the held-out
routes, none dropped) and dropped 9% of coin boxes on the clean game (134 of 1,466) and 7% on the
held-out routes (408 of 6,097); the dropped ones miss the coin by 0.8 coin-widths at the median.

How it got there, the same day, all on the same deployment:

1. Reading Glimmer's boxes as pixels, every robot box failed the check (runs 40934005706,
   40934009177): Glimmer answers on a 0-1000 grid (see "Coordinates" below).
2. With the grid, but a prompt that also gave the image's pixel size, Glimmer rescaled its x a
   second time on some frames (raw x about 1.6 times too small; run 40937863760). The grid prompt no
   longer gives the size, and the clean robot probe then kept 13 of 13 boxes (run 40940999505).
3. Requiring a box to contain the object's centre dropped 40% of coin boxes, and the real fix
   failed coins on 3 of 4 held-out routes (run 40941969395). A probe of how far the dropped boxes
   missed (run 40947089674, development frames only) found half within 0.13 of a coin of the
   centre and three quarters within half a coin: off by a few pixels, not elsewhere. The rule became
   "overlaps the engine's box", which is the same as allowing the centre to be up to half the
   object's size outside the box. The held-out routes were not used to choose it.
4. The same run failed the ground check on the clean game: Glimmer's robot box runs 15 to 20 pixels
   taller than the robot, too loose for the spec's 20-pixel tolerance. Under `glimmer-engine` the
   ground check is now judged on the position log against the clean level's ground line (the SAM-off
   ground check). The ground check then no longer sees sinking/v2 (the robot drawn 26 px low,
   physics unchanged), which SAM's hybrid fails on every route (docs/sam.md). The dev bench below
   still catches it, on player-always-visible, on 2 of 5 routes.

Held-out detection bench, judge `glimmer-engine` (no SAM key in the runs), every private bug
variant and the clean game, each on the smoke route and the four private routes, the same jobs and
checks as SAM's bench in docs/sam.md, under the overlap rule above, with the ground judged on the
position log against the clean level's collision and the floor as drawn (commit 92508d9, run
41003751876, Oct 30; `bench/detection/held-out-glimmer-engine.json`).

| Held-out variant | Engine | Gameplay | player-always-visible | coins-visible | Caught, Glimmer+engine | Caught, SAM on (docs/sam.md) | Caught, SAM off |
| --- | --- | --- | --- | --- | --- | --- | --- |
| clean (control) | 5 pass | 5 pass | 5 pass | 5 pass | **no false alarm** | no false alarm | no false alarm |
| physics-fall-through/v5 | 5 fail | 5 fail | 5 fail | 5 pass | **yes** | yes | yes |
| physics-fall-through/v6 | 5 fail | 5 fail | 5 fail | 5 pass | **yes** | yes | yes |
| missing-texture/v5 | 5 pass | 5 pass | 5 pass | 5 fail | **yes** | yes | no |
| missing-texture/v6 | 5 pass | 5 pass | 5 pass | 5 fail | **yes** | yes | no |
| layering/v5 | 5 pass | 5 pass | 5 fail | 5 pass | **yes** | yes | no |
| layering/v6 | 5 pass | 5 pass | 5 fail | 5 pass | **yes** | yes | no |
| sinking/v3 | 5 fail | 5 pass | 2 fail, 3 pass | 5 pass | **yes** | yes | yes |
| sinking/v4 | 5 fail | 5 pass | 5 pass | 5 pass | **yes** | yes | yes |

With Glimmer checked against the engine, 8 of 8 held-out variants are caught and the clean game
raises no false alarm: the same count as SAM. Without vision, 4 of 8. The two families only vision
catches, missing-texture and layering, are caught on every route by the check aimed at them, and
every check fails only where its bug is: coins pass on every route of every variant that does not
touch the coins.

The bench before it (main at 9e9dba4; runs 40986446779 for sinking/v3 and v4, 40986680262 for the
rest, Oct 30) had the same verdict on every route of the other seven and the clean game, and missed
sinking/v4, as SAM did. A check added afterwards catches it (docs/sam.md, "The drawn floor";
`bench/drawn-floor/`). That check is the engine's render, not a
model, and it was built after the miss, from the public game, without reading sinking/v4's patch,
so this is a check made for the class that was missed, not a blind catch.

The first bench (runs 40967826195 and 40975628695, Oct 29) ran under the earlier rule, where a box
had to contain the object's centre, because the overlap rule had not reached main when its branch
was cut. It caught the same 7, but the coins check also failed on 3 routes where nothing touched the
coins (one each on layering/v5, layering/v6 and sinking/v3). Under the overlap rule those pass on
all 5 routes, and the catches are unchanged, missing-texture's coins fails included. The private
frames are not published, so which frames caused the earlier fails is not known; the earlier rule
dropped 40% of coin boxes on the clean game against 9% now.

Development detection bench, judge `glimmer-engine` (no SAM key in the run), the public variants in
`bugs/` and the clean game on the same five routes and checks as SAM's dev bench in docs/sam.md,
under the overlap rule, with the ground judged on the position log (main at 2de3d9c; run
41001182605, Oct 30; recorded in `bench/detection/dev-glimmer-engine.json`). It ran before the
drawn floor, which changes no development verdict on the four public routes (`bench/drawn-floor/`).

| Development variant | Engine | Gameplay | player-always-visible | coins-visible | Caught, Glimmer+engine | Caught, SAM on (docs/sam.md) | Caught, SAM off |
| --- | --- | --- | --- | --- | --- | --- | --- |
| clean (control) | 5 pass | 5 pass | 5 pass | 5 pass | **no false alarm** | no false alarm | no false alarm |
| physics-fall-through/v1 | 5 fail | 5 fail | 5 fail | 5 pass | **yes** | yes | yes |
| physics-fall-through/v2 | 5 fail | 5 fail | 5 fail | 5 pass | **yes** | yes | yes |
| sinking/v1 | 5 fail | 5 pass | 2 fail, 3 pass | 5 pass | **yes** | yes | yes |
| sinking/v2 | 5 pass | 5 pass | 2 fail, 3 pass | 5 pass | **yes** | yes | no |
| missing-texture/v1 | 5 pass | 5 pass | 5 pass | 5 fail | **yes** | yes | no |
| missing-texture/v2 | 5 pass | 5 pass | 5 pass | 5 fail | **yes** | yes | no |
| layering/v1 | 5 pass | 5 pass | 5 fail | 5 pass | **yes** | yes | no |
| layering/v2 | 5 pass | 5 pass | 5 fail | 5 pass | **yes** | yes | no |

All 8 are caught and the clean game raises no false alarm, as with SAM. This page had expected a
miss on sinking/v2, since the ground check no longer sees it. It is caught by player-always-visible
on 2 of 5 routes, the same count as SAM's visibility check, so the catch is narrower than SAM's: the
hybrid fails it on all 5 routes, and a run on only the other 3 would miss it with Glimmer. As on the
held-out set, every check fails only where its bug is.

The run took 419 job minutes against 49 for SAM's dev bench, 25 to 64 minutes a job against about 5,
with three jobs sharing one replica (2 h 45 min end to end).

### Judge benchmark: fixes that only look right (Oct 31)

The judge benchmark ([docs/evaluation.md](evaluation.md)) with `glimmer-engine` as a fourth judge,
beside the other three, on the same 15 candidates: 8 that undo a seeded bug exactly and 7, written
by us, that only look right. One run, live (run
[41230177124](https://github.com/Expectrail/Expectrail/actions/runs/41230177124), commit aa234b3;
`bench/judge/glimmer/`).

| Judge | Good fixes accepted | Bad fixes accepted |
| --- | --- | --- |
| Expectrail, SAM on | 8 of 8 | 0 of 7 |
| Expectrail, Glimmer checked against the engine (no SAM) | **8 of 8** | **0 of 7** |
| Expectrail, SAM off | 8 of 8 | 3 of 7 |
| Muse from screenshots | 6 of 8 | 2 of 7 |

The other three judges gave the same counts as in the two October 29 runs (`bench/judge/`), Muse's
6 of 8 matching the first. What the reasons show:

- **The robot drawn behind the level art** fails `player-always-visible` under Glimmer, as under SAM.
- **The robot drawn inside the ground** passes the ground check under Glimmer, as expected: the
  ground is judged on the position log, and the physics is intact. `player-always-visible` stops it.
  SAM fails it on both checks.
- **One reject did not come from the check aimed at it.** The candidate that shows the robot by
  deleting every tree passed every public check under Glimmer, `player-always-visible` included.
  SAM fails that check on it, because the robot is still drawn behind the grass, bushes and tiles
  ([docs/evaluation.md](evaluation.md)). Under Glimmer it was stopped only by the ground check on a
  held-out route. What that route showed is a held-out detail and is not published; both good
  layering fixes pass every check on every route. **On the public checks alone, Glimmer checked
  against the engine would have accepted 1 of 7.** Its visibility check is looser than SAM's on a
  partly hidden robot.

Limits: one run of 15 cases, and the bad candidates were written by us, so 0 of 7 shows it holds on
known tricks, not on new ones. Glimmer's verification took 17 to 56 minutes a case with every case
sharing one replica (2 h 54 min end to end, 587 job minutes for all four judges). At $8 an hour,
the deployment cost about $24 for the run. That is an estimate from the run's length, not from the
bill.

## Muse Spark Open, live (Oct 30)

Two runs of the **Spark Open** workflow on public material (`bench/spark-open/`, one folder per
run). In each, `meta-models/muse-spark-open` on inference.baseten.co served all 6 calls with no
error, and Muse Spark on Meta's API drafted the same checks for comparison.

| Run | Spec prompt | Ground draft gives the approved spec's verdict, 9 seeded runs: Spark Open | Muse Spark |
| --- | --- | --- | --- |
| 41026508747 | `side` not defined | 3 of 9 (side "below": fails the clean game) | 9 of 9 |
| 41027140573 | `side` is where the object stays | **9 of 9** | 9 of 9 |

- The prompt listed the values of a boundary's `side` but not what it means, so Spark Open's reading
  (the side the robot must not go to) fitted it as well as Muse Spark's. The prompt now defines it,
  with an example that is not one of our checks. The 9 of 9 is one run after that change, at
  temperature 0, not a rate.
- All drafts in both runs were valid specs with the approved assertion type, and none would be
  approved as drafted. The object prompts are generic ("player", "ground", "coin" against "blue
  robot", "grass-topped ground", "gold coin"), the tolerance is 8 px against 20, and the window is
  every frame. A person tightens these, as with Muse Spark.
- The scripted playtest: all 7 remarks sorted as the fixed rules sort them wherever a rule applies,
  and both requests to switch a check off flagged by the model itself and sent to a person. The coin
  report was drafted as a `reaches` assertion, which is not what the remark says; "unsupported" was
  the right answer.
- About 4,000 tokens in and 6,000 to 7,000 out a run.

## What is not measured yet

- **How often a fine fix gets a false fail.** 8 of 8 correct fixes accepted in one judge benchmark
  run, and a clean game passing on 5 routes, is not a rate. A frame with one or two
  coins on screen, where Glimmer's only box misses by more than half a coin, would fail
  coins-visible on a game that is fine.
- **Confidence is self-reported, and flat.** Glimmer rates its own boxes from 0 to 1, and gave 0.90 to
  every coin on every frame. The evaluator's 0.5 threshold and the verifier's clean-score floor apply
  to that number, but it is not a margin the way SAM's scores are. Another reason `both` is the judge.
- **Speed.** 3 to 6 s a call with one or two runs on the deployment, 12 s with three sharing one
  replica. A verify run took about 30 to 40 minutes with either judge.
- **Coordinates (measured, Oct 29).** Glimmer answers on a 0-1000 grid over the image even when the
  prompt asks for pixels. Fitting its robot boxes against the engine's position on every probed
  frame (run 40936605897), its x came out 1.58 to 1.60 times smaller than the frame's pixels and its
  y 0.95 to 0.99 times: 1600/1000 and 960/1000. Converted, clean frame 0 reads [752, 662, 856, 797]
  against the engine's [760, 660, 840, 780]. Size alone had not shown it (on a 1600x960 frame a
  0-1000 box looks like pixels), which is how the earlier probes got it wrong. The prompt now asks for
  the 0-1000 grid and `EXPECTRAIL_GLIMMER_COORDS` defaults to `norm1000`. Boxes with corners in the
  wrong order, or more than 2% of the frame outside it, are refused (needs-review); read as pixels,
  a 0-1000 box near the bottom edge (y up to 1000 on a 960-pixel frame) was refused this way, which
  may be what stopped the one held-out coins check in run 40915475383.

## What is not built yet

- **Engine positions for other objects.** The engine check knows the robot and the coins. A spec
  about anything else (an enemy, a door) is needs-review under `glimmer-engine` until the harness
  logs it too.
- **A precise ground check without SAM.** Under `glimmer-engine` the ground is judged on the
  position log, so the ground check does not see a robot drawn into the ground with its physics
  intact (sinking/v2); only the visibility check catches it, on 2 of 5 routes. Glimmer's boxes are
  not precise enough for the ground check; another open-weight segmenter could be.

## Keys

`FIREWORKS_API_KEY` (or `EXPECTRAIL_GLIMMER_API_KEY`) and `BASETEN_API_KEY` (or
`EXPECTRAIL_OPEN_API_KEY`) are read from the environment or the gitignored `.env`. None of them is on
Muse Code's environment allowlist. The Glimmer key may not be the same as `META_API_KEY`, the key
the fixer holds. In CI, add the `FIREWORKS_API_KEY` repository secret; `both` also needs the SAM key
(`MODEL_API_KEY`). The workflow does not pass the SAM key to a `glimmer-engine` run.
