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
The table shows the expected verdict beside the one given. kinematic-character has two:

| Change | What it does | Expected | Why |
| --- | --- | --- | --- |
| `broken` | empties the player's collision mask, so it falls through the floor | reject | a real bug in a game we did not write; the approved check should see the player go below the ground |
| `harmless` | tints the player's sprite; nothing it does changes | needs-review | the engine's checks pass, as on the project unchanged, but CI has no vision key and an accept needs vision (#379). The engine's record alone gave accept on #398/#401, before vision was required; Sean withdrew call 4 for the engine's record, and an outside project counts as verified only after a run with vision |

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
