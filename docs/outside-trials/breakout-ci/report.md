# Breakout in the outside trial

The registered game is [mike0697/Breakout](https://github.com/mike0697/Breakout/tree/0ac7aed444ea593a023d9b666c211d7ab8acd51e), MIT, pinned to `0ac7aed444ea593a023d9b666c211d7ab8acd51e`. The source is fetched, not vendored. This keeps the choice and route from the [same-pin retrial](../breakout-pointer/report.md).

The original run below used the whole viewport for the paddle and inferred useful play from the paddle’s movement. The current drafts check the paddle’s vertical rail and require the Ball drawing itself to move after Start. The public registry now includes a control that stops the Ball while the Paddle still moves. [Paddle measurements](public-control-feasibility.md) · [Ball movement and stationary control](../../new-work/2026-11-20-bound-ball-movement.md)

## What ran locally

The actual trial runner fetched a new checkout at the pin, laid out the config/routes/draft checks, applied and reverse-checked the harmless/broken patches, and ran:

```sh
python3 -m tools.outside_trial --fetch --only breakout --execution-class diagnostic --out runs/outside
```

Godot 4.7.2 and Xvfb were used; no key, live model or approval. The local sandbox cannot create a user namespace, so this is **diagnostic evidence, not the isolated CI proof**. [Machine-readable results](outside-trial.json) and [the runner's report](outside-trial.md) are generated outputs, not hand-entered verdicts. Seconds include verification and the separate draft replay; `verifySeconds` records the verification portion.

| Copy | Gate | Paddle draft diagnostic | Ball draft diagnostic | Seconds |
| --- | --- | --- | --- | ---: |
| Pinned | needs-review | pass: 51 frames | pass: 11 frames | 58.3 |
| Harmless comment | needs-review | pass: 51 frames | pass: 11 frames | 59.8 |
| Broken, paddle x=8 | needs-review | fail: first checked frame 20, 51 failing frames | needs-review: paddle movement prerequisite not reached | 50.7 |

There are zero approved checks run in each gate job. The raw findings are **not** gate accepts/rejects. The registry at the time required these three needs-review decisions and every listed raw finding. A missing diagnostic, replay failure or changed expectation fails the trial command. An approved spec accidentally listed as a draft is refused, never relabelled unapproved.

## Why the paddle draft changed

The old draft's single left-lane checkpoint could pass a paddle frozen there. The new draft requires the bound paddle within 24 pixels of `[170.4, 616]` at tick 20 and `[50.4, 616]` at tick 70. These centres come from the saved route's pointer x at those ticks and the scene's paddle y. The tolerance is half the collision width (48/2), not a fitted observation error. The centres are 120 pixels apart, greater than the sum of their tolerances (48), so no frozen position can satisfy both. Both ticks lie in the bounds window, 20..70. All 51 window frames are required. Missing movement is not exercised, never a pass. A concrete out-of-bounds counterexample still fails.

The bounds are the actual viewport `[0, 0, 360, 640]` from `project.godot`. Side-wall inner surfaces are x=-0.25 and x=360.25; the paddle script clamps its collision to the viewport, and its 47×18 drawing fits the 48×19 collision. The region is therefore supported by the game data, not copied from the platformer. [Derivation, source hashes and pinned links](derivation.json). The timing window is authored policy, stated as such. Start releases at tick 14; tick zero and the menu are outside the check window.

The ball draft now uses a source-derived boundary y=204 (initial centre y=200 plus collision radius 4), instead of the previous unexplained y=300. Its whole drawing must be below that line during frames 40..50, with all 11 frames judged, and the same two paddle checkpoints establish useful play. This checks a seeded launch, not every bounce or brick. Broken still has valid ball observations but lacks the movement prerequisite, so the raw ball result is needs-review.

The [derivation script](derive-drafts.py) reads the public pinned scene/project data and saved route; it never calls a model or approves anything:

```sh
python3 docs/outside-trials/breakout-ci/derive-drafts.py breakout-source tests/outside/breakout-pointer derived-checks
```

## CI status at the time of the original run

**Not run on this pull request yet.** Sean pushes the local patch. Changes to `tests/outside/**` and `tools/outside_trial.py` trigger **Outside projects trial**, job **`outside-trial`**, in `.github/workflows/outside-trial.yml`. Its existing command is:

```sh
python -m tools.outside_trial --fetch --execution-class isolated --out runs/outside
```

It now reads the third registry entry and must show all three Breakout rows. Both its CLI verification and its separate draft captures require the replay sandbox; neither may fall back to diagnostic execution. Read the job's conclusion and the `outside-trial` artifact/summary before calling this integrated. No workflow edit or dispatch was made here.

Approvals and vision remain separate human work. The PR body states the exact checks and commands for Sean; this change writes no approval and does not close #263.
