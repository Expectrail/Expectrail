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

None recorded yet. The first run is the one on the pull request that added this page; its numbers
go here with the run's link, and nothing goes here without one.

## What reading the projects already showed

From reading, before any run (the full list is on #263):

- A route's presses were never delivered to a game that reads input as events. Fixed (#338).
- The player must be a node named `Player`; a coin a class `Coin`; and so on. Nothing can say
  otherwise yet (#259).
- Ground is read from tile collision only. Dodge the Creeps has none.
- No approved check fits a top-down game. A project with no check that fits is needs-review.
- A route cannot click, and cannot press a key that is no action.
