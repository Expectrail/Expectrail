# Outside projects

Godot projects the team did not write, verified with the command a stranger would run. This page
holds only what a recorded run shows, with its link. A project a builder wrote for a test
(`tests/projects/`) is not an outside project and is never counted here.

## How it runs

`tests/outside/projects.json` pins each project to a repository and a full commit. The workflow
`outside-trial.yml` fetches each one at that commit (nothing of the project is copied into this
repository), lays out a checkout with our own routes and the bundled approved spec, and runs
`expectrail verify` on it. The job holds no secret, has a read-only token, and requires the replay
sandbox for every replay, because the projects' code is not ours.

A project may also list **changes**: small patches of ours under `tests/outside/<project>/changes/`,
each with the verdict it should get. For each one the project as pinned is the base and a patched
copy is the head, and `expectrail verify --base` judges the change as it would judge a pull request.
The table shows the expected verdict beside the one given. kinematic-character has three:

| Change | What it does | Expected | Why |
| --- | --- | --- | --- |
| `broken` | empties the player's collision mask, so it falls through the floor | reject | a real bug in a game we did not write; the approved check should see the player go below the ground |
| `harmless` | tints the player's sprite; nothing it does changes | needs-review | the engine's checks pass, as on the project unchanged, but CI has no vision key and an accept needs vision (#379). The engine's record alone gave accept on #398/#401, before vision was required; Sean withdrew call 4 for the engine's record, and an outside project counts as verified only after a run with vision |
| `invisible` | hides the player's sprite; it moves exactly as before | needs-review | a defect only a visual observer can see (#330): the engine's checks pass, as on the project unchanged. Without vision it is needs-review like any accept; with vision it must stay needs-review, because no player is drawn where the engine says it is. If a vision run ever accepts it, the visual observer is not looking |

**The first run did not test either change.** [Run 43398657245](https://github.com/Expectrail/Expectrail/actions/runs/43398657245)
on PR #385 gave all three kinematic-character rows the same verdict, needs-review, with the same
numbers ("no violation in 77 frames judged, but an object was not found in 43 frames"). The broken
copy should have been rejected. The cause was in the trial, not in the verifier: CI lays the
checkouts out inside this repository, and `git apply` run there read the patch's paths from the
repository's top, skipped the file, and exited 0 with nothing changed. So the "broken" and
"harmless" heads were the project unchanged. The trial now keeps `git apply` from finding a
repository above the checkout, and proves each patch took by applying it in reverse as a check; a
test reproduces the case inside a repository.

**The run after the fix: the broken copy is rejected, the first outside verdict that is not
needs-review.** [Run 43404391367](https://github.com/Expectrail/Expectrail/actions/runs/43404391367),
every replay in the sandbox, the bundled approved check copied unchanged:

| kinematic-character | Verdict | Expected | Seconds | What the check said |
| --- | --- | --- | --- | --- |
| as pinned | needs-review (exit 2) | - | 14.8 | "no violation in 77 frames judged, but an object was not found in 43 frames (first 0)" |
| broken: the player's collision mask emptied | **reject** (exit 1) | reject | 13.4 | "player is 71.749px past the boundary (above 304.5, tolerance 20) (first at frame 44, 10 frames)" |
| harmless: the player's sprite tinted | needs-review (exit 2) | needs-review | 13.3 | the same as the project as pinned |

What the engine logged around frame 44 of the broken copy: the player falling at about 3 px a tick
(y 341.6 at tick 82 to 372.0 at tick 92) through a surface the engine reports at y 304 under it, and
never on the floor. The ground line under the player moves between 464 and 304 as it passes the
columns of a platform, and the check measures from the surface in its own column. So the reject is
for the right reason: the player went through something solid.

What this shows and what it does not: a bug we planted in a game we did not write is rejected by a
check written for another game. It does not show that a correct change to this game can be
accepted. The harmless change and the project as pinned are both needs-review, because 43 of 120
frames have nothing logged under the player (it starts in the air, and moving platforms are bodies,
not tiles). That needs a check written for this game and approved by a person. The patch is ours:
this is a seeded bug, not one found in the wild.

**Platforms that are bodies now count as ground (#388).** [Run 43428126877](https://github.com/Expectrail/Expectrail/actions/runs/43428126877),
with the harness reading the ground from the level's platform bodies as well as its tiles (a platform
counts only at or below the player's feet):

| kinematic-character | Verdict | Frames judged | Frames with no ground |
| --- | --- | --- | --- |
| as pinned | needs-review | 115 of 120 (was 77) | 5, from frame 38 (was 43, from frame 0) |
| broken | **reject**, the same as before: 71.7 px past the surface at 304.5 from frame 44 | | |
| harmless | needs-review, the same as the project as pinned | 115 of 120 | 5 |

No violation in the 115 frames judged of the clean game. The first version of this change, which let
a platform up to 64 px above the player's origin count, rejected the clean game
([run 43422746940](https://github.com/Expectrail/Expectrail/actions/runs/43422746940)): a wrong reject
found by this trial and fixed before merging. Dodge the Creeps is unchanged: it is seen from above and
has no ground at all, so a ground check never applies to it.

The five frames left (ticks 76 to 86) turned out not to be over nothing: the player is in the air over
a pit whose floor is tile row 29, and the harness read only 16 tile rows down, so its search ended at
row 27 (the engine rows printed on #397, run 43476562502). See the next section.

**The ground is read down to the level's last row (#398).** [Run 43484520696](https://github.com/Expectrail/Expectrail/actions/runs/43484520696/job/132089304010),
with the tile search going to the last row each layer uses instead of 16 rows (platforms that are
bodies already had no depth limit):

| kinematic-character | Verdict | Expected |
| --- | --- | --- |
| as pinned | **accept**, all checks pass | - |
| broken | **reject**: 71.7 px past the surface at 304.5 from frame 44, 10 frames | reject |
| harmless | **accept**, all checks pass | accept |

Dodge the Creeps is still needs-review, correctly: no frame has a ground. These are the first accepts
on a game the team did not write. They are accepts on the engine's record, from one generic public
check (`player-stays-above-ground`) on one route, with no vision model asked. On November 13, 2026
Sean withdrew the product manager's call 4 (needs-review until a check written for the game is
approved) for the engine's record, and set the bar for "verified": an outside project counts as
verified only after a run in which vision has looked at it too (#327, #379). That run has not been
made, so **no outside project counts as verified yet**.

**From #392 on, the trial runs without vision and says so.** `expectrail verify` now needs a vision
model to accept (#379). CI has no key, so the engine's checks still run (a failure rejects) and a pass
is needs-review with a `PROVIDER_FAILED` diagnostic naming the missing setting. The expected verdicts
are therefore: as pinned, needs-review; broken, reject; harmless, needs-review. The engine's own pass
on the clean and harmless runs is unchanged from run 43484520696 above.

It is a trial, not a gate. A needs-review or a reject is a finding to read; the job fails only when
a project cannot be fetched as pinned or the command ends with no verdict.

```sh
python -m tools.outside_trial --fetch --execution-class isolated --out runs/outside
```

## Reading an outside vision run

Sean starts **Outside vision** from the Actions tab on main, chooses a project and sets one
positive dollar cap for the whole run (at most $2). The capture job fetches the pinned commit,
applies each listed change to its own copy and requires the replay sandbox for every route.
The `outside-captures` artifact holds the replay records, traces and frames for `pinned` and
each change. The capture job passes a digest of those records to the judge as a job output.

Only the judge receives the model key. It checks the capture digest, route bytes, sandbox
record, trace and frame hashes before asking SAM. It reads the spec and routes from Expectrail's
own checkout. A missing capture, a changed frame or a bad hash stops judgement.

Read the job summary one row at a time. The pinned row judges the original project. Each change
is compared with that same pinned base. **Verdict** is the gate's decision. **Expected** comes
from the trial list, including expectations written for the earlier run without a vision key.
A difference is a result to investigate. Open `outside-vision-findings` for each variant's
`findings.json`. Its `checks[].observed` entries say what the engine and vision actually saw.
A failure on either rejects. An engine failure can reject before vision is asked about that
check. An accept needs both observers to pass the applicable checks. Missing vision evidence
keeps an engine pass at needs-review. The summary and `spend.json` report the requests,
images answered and amount reserved at list price, including tries that failed.

For #263, “verified” needs a recorded run on the pinned outside project in which vision
actually judged the evidence. Read the observer entries and verdicts for the pinned project
and its changes. A successful workflow alone establishes no project result. Sean records the
first kinematic-character run and its verdicts on #263 and decides the public wording.

## The projects

| Project | From | Kind | Why it was chosen |
| --- | --- | --- | --- |
| kinematic-character | `godotengine/godot-demo-projects`, `2d/kinematic_character`, commit `b761b4c`, MIT | platformer with moving and one-way platforms | the nearest thing to the bundled game that is not the bundled game: what breaks here breaks for every platformer |
| dodge-the-creeps | the same repository and commit, `2d/dodge_the_creeps`, MIT | top-down, no tiles, enemies at random, starts from a button | the game of Godot's own first tutorial, and unlike the bundled game in every way that matters |

Both come from the Godot organisation's demo repository. That is a cautious first choice, not the
end of it: a project from outside that organisation should replace one of them before these count
for the release (#263). The demo repository's `2d/platformer` is not here because it is the
bundled game.

## Results

**November 12, 2026, after two fixes: both projects, unchanged, are needs-review.** No wrong reject
is left, and neither project is accepted.

[Run 43289338556](https://github.com/Expectrail/Expectrail/actions/runs/43289338556/job/131431091194),
on the pull request for #348 merged with main (which has #346), every replay in the sandbox:

| Project | Verdict | Seconds | What the check said |
| --- | --- | --- | --- |
| kinematic-character | needs-review (exit 2) | 9.2 | "no violation in 77 frames judged, but an object was not found in 43 frames (first 0); a missing object is never a pass" |
| dodge-the-creeps | needs-review (exit 2) | 11.9 | "no violation in 0 frames judged, but an object was not found in 120 frames (first 0); a missing object is never a pass" |

- Dodge the Creeps has no ground, and the check now says it cannot tell (#346).
- On the platformer the player is judged above its ground in the 77 frames that have a ground
  line, the frames beside the step included: the ground's edge columns are now the player's own
  width, 14 px, and not the bundled robot's (#348). In 43 frames nothing is logged under the
  player. It starts in the air; the rest were not looked at (in the air, or on a platform that is
  a body and not a tile).
- An earlier head of the same pull request, with a rule that was withdrawn, gave needs-review with
  99 frames judged ([run 43278306020](https://github.com/Expectrail/Expectrail/actions/runs/43278306020/job/131392534912)).
- Needs-review is the honest answer for both and it is not a pass: no check written and approved
  for either game exists, a broken version of either has not been tried, and no vision model was
  asked. No outside project counts as verified.

### The first runs, before the fixes

**November 12, 2026: both projects, unchanged, are rejected.** These are clean projects from the
Godot organisation with no change made to them. A reject of a clean game is a wrong verdict, and
it is the first thing Expectrail said about a game the team did not write.

[Run 43265350277](https://github.com/Expectrail/Expectrail/actions/runs/43265350277/job/131347312568),
every replay in the replay sandbox, the one approved check the repository has (written for the
bundled game, copied unchanged), one route of ours for each project:

| Project | Verdict | Seconds | What the check said |
| --- | --- | --- | --- |
| kinematic-character | reject (exit 1) | 13.4 | "player is 70.017px past the boundary (above 272.5, tolerance 20) (first at frame 92, 28 frames)" |
| dodge-the-creeps | reject (exit 1) | 12.4 | "player is 450px past the boundary (above 0, tolerance 20) (first at frame 10, 110 frames)" |

The first run, [43264589901](https://github.com/Expectrail/Expectrail/actions/runs/43264589901/job/131344660031),
gave the same two verdicts in 7.9 and 9.1 seconds.

What this shows, and what it does not:

- **Dodge the Creeps has no ground, and the check read "no ground" as a ground at 0.** A measurement
  that cannot be made must be needs-review. Here it became a boundary, and a clean game was
  rejected on it. That is a fault in the verifier, whatever game it is pointed at.
- **The platformer's ground line is wrong for that level.** The player is reported 70 px below a
  ground at 272.5 while walking and jumping on a level that has moving and one-way platforms. Why
  is not known yet: the record was not read beyond this line.
- **The check was never approved for these games.** It was written and approved for the bundled
  game, and the trial copies it unchanged, as the tests of a second project do. A stranger's
  project has no approved check at all, and the right answer for it today is needs-review ("no
  checks ran"). So this run is not what a stranger would see first; it is what happens when the
  only check the product has meets a game it was not written for. It rejects where it should say
  it cannot tell.
- Both games started, were driven by a route and replayed inside the sandbox in under 15 seconds.
  Dodge the Creeps starts from a button's shortcut, which could not be pressed before #338.
- Not shown: a broken version of either project being caught, a harmless change being accepted, or
  anything about the time a person would need. No outside project counts as verified.

## What reading the projects already showed

From reading, before any run (the full list is on #263):

- A route's presses were never delivered to a game that reads input as events. Fixed (#338).
- The player must be a node named `Player`; a coin a class `Coin`; and so on. Nothing can say
  otherwise yet (#259).
- Ground is read from tile collision only. Dodge the Creeps has none.
- No approved check fits a top-down game. A project with no check that fits is needs-review.
- A route cannot click, and cannot press a key that is no action.

## First outside game verified with vision (November 14, 2026)

[Run 43652198623](https://github.com/Expectrail/Expectrail/actions/runs/43652198623) (outside-vision.yml,
dispatched by Sean on main after #470; 800 images, $2.00 at list price, which reached the run's cap).
The anchored observer's calibration on the unchanged game was **used**: found at its place in 19 of
19 frames, drawn size matching the collision box in 19 of 19, the nudged point giving the same answer
in 19 of 19 (`tests/outside/recordings/kinematic-character/calibration.json`).

| Change | Verdict | Engine | Visual observer |
| --- | --- | --- | --- |
| none (as pinned) | **accept** | 1 of 1 pass | agrees |
| broken (collision mask emptied) | **reject** | fails: 71.7 px past the ground, from frame 44 | agrees |
| harmless (sprite tinted) | **accept** | 1 of 1 pass | agrees |
| invisible (sprite hidden) | **reject** | passes | fails: 77.5 px past the ground, from frame 0 |

Read the last row plainly: with no sprite drawn, the model answered at the player's place with
something else (what lies behind the player), and that reaches below the ground line. The verdict is
right (a hidden player is never accepted); the stated reason is indirect, not "no player drawn".
`tests/outside/projects.json` keeps needs-review as the expectation for `harmless` and `invisible`,
because the CI outside trial has no vision.

The run's answers are kept in `tests/outside/recordings/kinematic-character/vision-recording.json` (429
answers). They replay for free with `tools/outside_vision.py judge --recording`, but only for frames
whose bytes match the ones recorded; whether a fresh capture reproduces them is not yet checked.

## Anchored vision (#330)

**Why the first vision run found no player.** The outside judge asked every game the bundled game's
spec, whose player prompt is "blue robot". Kinematic-character's player is a grey square, so the
model found it in 0 of 120 frames (run 43559500793). Words cannot name a player nobody described.

**What the judge asks now.** `tools/outside_vision.py judge` uses `expectrail/anchored.py`: in each
frame the model is asked what is drawn at the middle of the engine's collision box for the player
(the trace's `body`). A point carries no size the answer could copy. The spec's assertion is judged
on the box the model answers with. A provider failure remains needs-review. After calibration,
a successful empty or wrong-sized answer is missing-player evidence; three consecutive such
observations reject (#481), rather than measuring the background as the player.

**When it is used.** Only for a game whose clean run passes these rules (`RULES` in
`expectrail/anchored.py`), set by Sean on November 14, 2026 after the first live calibration:

| Rule | Threshold |
| --- | --- |
| Found: a box holding the asked point | at least 90% of asked frames |
| Size: that box within 25% or 4 px of the engine's collision box, whichever is larger | at least 90% of found frames |
| Stable: a point nudged 3 px, still inside the collision box, gives the same box (within 25% or 3 px) | at least 90% of found frames |
| Frames asked | at least 8 (every tenth clean frame) |

The stable rule is the guard against a model that answers with whatever is near the point. A game
that fails any rule keeps no visual observer, and its verdicts stay needs-review. The calibration
(`calibration.json`, `expectrail.vision-calibration/v1`) is published with every run, and a
calibration whose verdict does not follow from its own frames, or that uses other rules, is refused.

**The first live calibration** ([run 43609849950](https://github.com/Expectrail/Expectrail/actions/runs/43609849950),
$0.095, 38 images) asked with a box (the collision box widened 4 px) and tested stability with a
box twice as large. It found the player in 19 of 19 frames, and the answers were 16 to 19 px for a
16 px sprite over a 14 px collision box. But the larger box took in the tiles around the player
(30 to 62 px), and 25% of 14 px is 3.5 px, so it was not used (size 42%, stable 0%). That led to the
point question and the pixel floors above.

**The second live calibration** ([run 43643679280](https://github.com/Expectrail/Expectrail/actions/runs/43643679280),
$0.0475, 19 images) asked with points: found at its place in 19 of 19 frames, drawn size within the
rules in 19 of 19, but the nudged point gave the same answer in 0 of 19, so it was not used. Both
points went in one request as two objects, and the model gives each pixel to one object, so the
second point on the same 16 px sprite came back without the sprite. The nudged point is now asked in
its own request (26 images for a calibration).

**Recorded once (Option A).** The live judge wraps the model in a recorder and leaves
`vision-recording.json` in the run's artifact. `judge --recording FILE` replays those answers with no
key and no spend; a frame or question not in the recording gets no answer.

Not yet measured: nothing above says how the live model does on kinematic-character. That is the
first live run after this lands.

## Optional vision sampling and repeated questions (#330)

`python3 -m tools.outside_vision judge` accepts `--vision-every N`. The default is **1**:
vision examines every captured frame in each check's window. A larger positive integer is an
explicit trade-off, subject to the check's shared `sampling_plan`: eligible checks examine every
Nth frame from the window's first, plus its last. Fractional `visible` checks (a `minFraction`
below 1), unknown assertion types and explicit frame-count/share obligations use every frame.
For example, add `--vision-every 4` to a judge command over a saved capture. The capture command
and workflows keep their current defaults; this does not add a paid workflow dispatch option.

The engine still checks every frame and the gate still requires the complete capture. Only the
anchored observer's point questions are sampled. Calibration keeps its two questions per selected
clean frame, every tenth frame plus the last. The paired gate comparison keeps its own box
questions and stride 10. Specs with explicit coverage obligations keep their full-window
requirements and may need review when the visual evidence is sampled.

**What sampling can miss:** a visual defect shorter than N frames can fall between samples.
A sampled non-pass triggers questions on every remaining frame before a verdict is used.
This can find a `reaches` witness between samples, or show that three negative samples were
not consecutive missing-player frames. If refinement cannot finish, the gate needs review.
A sampled `reaches` witness may pass; explicit coverage obligations still require their full window.
The missing-player rule still needs three consecutive negative observations, now checked against
the refined full sequence before rejecting. Findings record the requested opt-in in
`observers.visionEvery` (absence means 1). Saved observations record the effective rate in
`analysis.every` (1 after full refinement) and the additional frame numbers in `analysis.refined`.
The report reader and run summary name the requested stride. No approved spec is changed.
The [offline policy tests](../tests/test_vision_sampling_policy.py) exercise these rules.

The outside judge now reuses a successful answer to the **same PNG bytes, question kind and exact
prompt** within that judge invocation, including calibration and all variants. It also reuses an
empty answer, which is evidence; it does not cache provider errors or unknown recording keys.
A point question and a box question remain different requests. The previous recording wrapper
removed duplicate keys from its final JSON but still sent each repeated live question. Other
recording callers retain that behavior unless they explicitly request reuse.

### Where the first run's images went

Source: the code at run commit `89ce6ff6ee8324da03c45be4bbdb944c091289cf`, its saved capture,
[run 43652198623's judge log](https://github.com/Expectrail/Expectrail/actions/runs/43652198623/job/132623245351),
and its checked-in [calibration](../tests/outside/recordings/kinematic-character/calibration.json)
and [answers](../tests/outside/recordings/kinematic-character/vision-recording.json).
The log reports **802 requests, 800 images answered, $2.00**, at the cap. Those totals are
run-log evidence. The per-phase allocation below is **not reproducible from this pull request**:
its reconstruction used a downloaded capture and a handover-only script, neither committed here.
It is a historical allocation claim, not validation of the current sampling implementation.

| Variant | Calibration | After observer | Before observer | Paired comparison before / after | Answered images | Requests |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pinned | 38, shared once | 120 | 0 | 0 / 0 | 158 | 158 |
| Broken | 0 | 0 | 120 | 19 / 7 | 146 | 146 |
| Tinted (harmless) | 0 | 120 | 120 | 19 / 19 | 278 | 278 |
| Hidden (invisible) | 0 | 120 | 98 | 0 / 0 | 218 | 220 |
| Total | 38 | 360 | 338 | 38 / 26 | 800 | 802 |

Calibration is 19 clean frames with two separately asked points. Each check window is 120 frames;
the capture has 180. Broken fails the engine check, so its after observer is not asked; its paired
comparison can ask only seven after frames because the player leaves the frame. Hidden exhausts
the cap during its before observer: one blocked request there, then one blocked request at the
start of its paired comparison. These were not two extra answered images.

The earlier November 15 offline lookup comparison below is **not reproducible from this pull
request**: its capture, script and logs were handover-only. It predates the sampling-policy
rework and must not be used as evidence for this revision's decisions or request savings.

| Judge setting | Questions reaching the recording | Answered | Not recorded | Pinned / broken / tinted / hidden |
| --- | ---: | ---: | ---: | --- |
| Reuse exact answers, stride 1 | 448 | 429 | 19 | accept / reject / accept / reject |
| Reuse exact answers, stride 4 | 187 | 168 | 19 | accept / reject / accept / reject |

The 19 absent answers are hidden-variant box prompts that the capped run never answered. They
remain unknown; they are not invented or used to accept. The hidden player's point observations
were reported as rejecting in that earlier comparison. Its uncached baseline and cached stride 1
were reported as giving the same four decisions. These historical counts
are recorded-answer lookups, **not a measured new live cost**, and say nothing about other games
or a new capture's ability to reproduce the PNG bytes. Stand-in tests additionally demonstrate
that a three-frame defect can be missed at stride 4 while the default rejects it.
