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

It is a trial, not a gate. A needs-review or a reject is a finding to read; the job fails only when
a project cannot be fetched as pinned or the command ends with no verdict.

```sh
python -m tools.outside_trial --fetch --execution-class isolated --out runs/outside
```

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

[Run 43278306020](https://github.com/Expectrail/Expectrail/actions/runs/43278306020/job/131392534912),
on the pull request for #348 merged with main (which has #346), every replay in the sandbox:

| Project | Verdict | Seconds | What the check said |
| --- | --- | --- | --- |
| kinematic-character | needs-review (exit 2) | 12.7 | "no violation in 99 frames judged, but an object was not found in 21 frames (first 0); a missing object is never a pass" |
| dodge-the-creeps | needs-review (exit 2) | 12.1 | "no violation in 0 frames judged, but an object was not found in 120 frames (first 0); a missing object is never a pass" |

- Dodge the Creeps has no ground, and the check now says it cannot tell (#346).
- On the platformer the player is judged above its ground in the 99 frames that have a ground
  line, the frames beside the step included (#348). In 21 frames there is no ground line: the
  player starts in the air (at tick 0 it is not on a floor and nothing is logged under it). Whether
  the other frames are in the air or on a platform that is a body and not a tile was not looked at.
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
