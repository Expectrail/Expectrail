# Outside projects

Godot projects the team did not write, verified with the command a stranger would run. This page
holds only what a recorded run shows, with its link. A project a builder wrote for a test
(`tests/projects/`) is not an outside project and is never counted here.

## Third independent-author trial: November 15, 2026

**System Override** (`aleshg/SystemOverride`, MIT, pin
`f95712a9e88480251e3ba38880d7144bf3f7b33a`) was chosen before inspecting its
integration, then fetched at that pin. It was **not onboarded successfully** and
was not swapped for an easier game. The
[choice, numbered command/stop log and recorded job documents](outside-trials/system-override/report.md)
are the evidence; no game was vendored and it is not in the working trial list.

| Third-project attempt | What worked | What did not | Product result / engine finding |
| --- | --- | --- | --- |
| inspect / init / manual draft | input map read; unresolved draft written; completed config, route and check validate | menu has no player; generated route presses exit/restart | one draft check, zero approved checks |
| headless automatic route | began replay 1 of 3 | player not found on any tick; config entryScene is not used for replay selection; .NET toolchain also unresolved | stopped, no route written |
| pinned | job recorded | display and disk preflight | needs-review / not run |
| harmless comment | applied patch and reverse-check passed | same preflight | needs-review / not run |
| hidden spaceship | applied patch and reverse-check passed | same preflight; no bug-detection evidence | needs-review / not run |

No core change was made for this trial; it used the pending role-box prerequisite.
The failed config-only path is recorded as a trial failure, not a pass on no
measurements. [Issue text](outside-trials/system-override/issues.md) covers scene
selection, toolchain refusal and a deleted diagnostic log. Human minutes were
not measured; command times and every attempted command are recorded separately.
No check was approved and no model was called. The two earlier demo projects'
results below are unchanged by this trial.

## Current evidence: November 15, 2026

The latest trial on merged [PR #473](https://github.com/Expectrail/Expectrail/pull/473) is
[run 43748180876](https://github.com/Expectrail/Expectrail/actions/runs/43748180876).
Its `outside-trial` job concluded **success**. The verdicts below come from
[`outside-trial.md` and the per-job findings in its artifact](https://github.com/Expectrail/Expectrail/actions/runs/43748180876/artifacts/14175650515),
not from the workflow conclusion alone. Every replay required the sandbox. Both projects use
MIT-licensed `godotengine/godot-demo-projects` at
`b761b4cd5718a7118f2c95eb55f181d0a5f004f1`.

| Project | Variant | Engine check | Product verdict without vision | Machine seconds |
| --- | --- | --- | --- | --- |
| kinematic-character | pinned | pass | needs-review | 7.4 |
| kinematic-character | broken collision | fail, first at frame 44 | reject | 11.8 |
| kinematic-character | harmless tint | pass | needs-review | 11.3 |
| kinematic-character | invisible sprite | pass | needs-review | 11.5 |
| Dodge the Creeps | pinned | pass | needs-review | 8.5 |
| Dodge the Creeps | broken clamp | fail, first at frame 97 | reject | 15.2 |
| Dodge the Creeps | harmless comment | pass | needs-review | 15.4 |

These are verification command times, **not human setup minutes**. No outside project is accepted
without vision under the current rule. For kinematic-character, the separate
[first vision run](#first-outside-game-verified-with-vision-november-14-2026) accepted pinned and
tinted copies and rejected the broken and invisible copies. No corresponding Dodge vision run is
recorded here. The audit also found that the vision judge ignored the selected Dodge spec and
used the bundled ground check; this change makes both trial paths use the same selection, tested
with saved stand-in captures. It is not a new live Dodge result. A ground check measures the platformer's floor crossing; Dodge's approved bounds
check measures the in-play origin against the viewport, not collisions, enemies, scoring or drawn art.

Dodge's broken copy first escapes at frame 97 (tick 97), with origin x = 486.666 beyond the
480-pixel viewport. Its converted box is `[459.666, 395.25, 513.666, 463.25]`; the allowed region is
`[-27, -54.75, 507, 733.25]`. The finding counts 153 out-of-bounds frames and 58 hidden frames as
**not exercised**, never passes. The initial hidden origin is no longer a false rejection.
Sean's content-bound approval of the updated spec is on main; this audit does not change it.

The complete onboarding trial is still missing: a timed `doctor` → `init` → route → clean
calibration → person-approved checks → three-variant verification session for each project.
Each currently has one check, not the requested two or three. Static inspection command timings
are in [the inspection work log](new-work/2026-11-14-draft-project-inspection.md); they do not measure
human setup. Core changes were needed to fit these games (#338, #346, #348, #388, #398 and #473),
so the historical trial did **not** prove configuration-only onboarding without core edits.
The [case-by-case audit](new-work/2026-11-15-project-audit.md) lists remaining evidence and Sean's steps.

The older sections below retain the progression of the trial. Their dated limitations describe
those runs, not the current results above.

## How it runs

`tests/outside/projects.json` pins each project to a repository and a full commit. The workflow
`outside-trial.yml` fetches each one at that commit (nothing of the project is copied into this
repository), lays out a checkout with our routes and the spec named by the project, and runs
`expectrail verify` on it. The job holds no secret, has a read-only token, and requires the replay
sandbox for every replay, because the projects' code is not ours. A project that omits `spec`
gets the bundled ground check, as kinematic-character does.

A project may also list **changes**: small patches of ours under `tests/outside/<project>/changes/`,
each with the verdict it should get. For each one the project as pinned is the base and a patched
copy is the head, and `expectrail verify --base` judges the change as it would judge a pull request.
The table shows the expected verdict beside the one given. kinematic-character has three:

| Change | What it does | Expected | Why |
| --- | --- | --- | --- |
| `broken` | empties the player's collision mask, so it falls through the floor | reject | a real bug in a game we did not write; the approved check should see the player go below the ground |
| `harmless` | tints the player's sprite; nothing it does changes | needs-review | the engine's checks pass, as on the project unchanged, but CI has no vision key and an accept needs vision (#379). The engine's record alone gave accept on #398/#401, before vision was required; Sean withdrew call 4 for the engine's record, and an outside project counts as verified only after a run with vision |
| `invisible` | hides the player's sprite; it moves exactly as before | needs-review | a defect only a visual observer can see (#330): the engine's checks pass, as on the project unchanged. Without vision it is needs-review like any accept; with vision it must not accept. The recorded vision run below rejects it; #481 makes repeated missing-player evidence say “not drawn” |

### Dodge the Creeps checks the player's position

Dodge clamps the player's origin between zero and the size of its viewport. Its check uses
`inside-region` over the `dodge` route, judging in-play frames. The gate represents the origin as
a box whose size comes from the clean replay's measured collision body. To include legal positions
right on an edge, the region extends by the converted box offsets on each side. With the pinned
scene's fixed view and native window size, this tests the recorded origin. It does not test sprite
drawing or collision interactions.
[Pinned player script](https://github.com/godotengine/godot-demo-projects/blob/b761b4cd5718a7118f2c95eb55f181d0a5f004f1/2d/dodge_the_creeps/player.gd)
and [viewport settings](https://github.com/godotengine/godot-demo-projects/blob/b761b4cd5718a7118f2c95eb55f181d0a5f004f1/2d/dodge_the_creeps/project.godot).

To reproduce the region from a checkout of that pin, run
`python3 -m tools.dodge_play_area /path/to/2d/dodge_the_creeps/project.godot --trace /path/to/clean/trace.json`.
Compare the result with `assertion.region.box` in [the Dodge spec](../tests/outside/specs/dodge-play-area.json).
Sean approved its current content on November 15, 2026. The `coverage.whenPlayerVisible` rule excludes
pre-round hidden frames as not exercised and still requires 120 judged frames. Changing its content
requires a new personal approval; do not carry the old approval onto a changed spec.

| Dodge change | Recorded CI verdict (run 43748180876) | Evidence to look for |
| --- | --- | --- |
| Remove the position clamp | reject | The route holds right long enough to cross the right edge. Check the finding for the first out-of-bounds position. |
| Change a comment | needs-review | The engine passes the same bounds check as the unchanged game. Vision did not run. |

Run 43748180876 above uses the play-area check. The earlier ground-check runs below remain historical evidence.

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
verified only after a run in which vision has looked at it too (#327, #379). At that point the vision run had not been made. The November 14 vision run below subsequently
verified kinematic-character on its recorded route; Dodge still has no recorded vision accept.

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
whose bytes match the ones recorded. #515 measured renderer drift at frame 111: exact lookup can
miss when the renderer differs. This is a limitation of replaying recorded answers, not a new live
vision result; see [the renderer work log](new-work/2026-11-15-recorded-renderer.md).

## Anchored vision (#330)

**Why the first vision run found no player.** The outside judge asked every game the bundled game's
spec, whose player prompt is "blue robot". Kinematic-character's player is a grey square, so the
model found it in 0 of 120 frames (run 43559500793). Words cannot name a player nobody described.

**What the judge asks now.** `tools/outside_vision.py judge` uses `expectrail/anchored.py`: in each
frame the model is asked what is drawn at the middle of the engine's collision box for the player
(the trace's `body`). A point carries no size the answer could copy. The spec's assertion is judged
on the box the model answers with, and missing evidence is never a pass. After #481, three consecutive frames with an explicit
not-drawn answer or an answer whose size cannot be the calibrated player reject with a not-drawn
reason; provider failures and unrecorded questions remain needs-review.

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

The calibration history above preceded the full vision run. Its measured four-variant result is
reported in “First outside game verified with vision” above; it does not establish general accuracy.
