# Public Breakout paddle bounds and Ball coverage (#716)

## What changed

Documented the horizontal range the existing route exercised, the paddle's authored drawing and collision bands, and the ball's launch and missed paddle. Compared a clean trace with two stationary-Ball controls using the existing draft evaluator. The baseline paddle draft used the whole viewport. The public draft now keeps the full playfield width and uses the collider’s actual vertical envelope, y=606–625. The generator reads the collider offset from the pinned scene. The two existing movement checkpoints and the 51-frame obligation still apply. Named Ball coverage through the current binding remains needs-review.

## What was run

The [public control report](../outside-trials/breakout-ci/public-control-feasibility.md) includes reproduction commands, versions and results. Godot 4.6.3 replayed the public seed-1 route for 407 physics ticks. All 407 Ball drawing boxes matched the previously published Godot 4.7.2 clean trace. The current Ball draft passed clean, failed a synthetic Ball held at spawn, and passed one held from tick 40. Two temporary Ball checkpoints returned unknown even on clean play.

Twelve rendered diagnostic replays covered the pinned game, harmless edit, paddle escape and empty input three times each. The revised paddle draft passed all six positive runs, failed at frame 20 in all three escape runs and returned needs-review in all three empty-input runs. The targeted suite (`python3 -m unittest tests.test_breakout_paddle_rail tests.test_outside_root tests.test_outside_trial`) ran 41 tests successfully. The new regression failed for both synthetic displacements before the draft was tightened.

## Not done

A paddle-hit route, wall-contact controls and a game-level frozen-Ball variant were not run. The two stationary controls used copies of the public recorded trace. The Ball coverage diagnostic used temporary in-memory conditions.

## Files

- [Public control feasibility](../outside-trials/breakout-ci/public-control-feasibility.md)
- [Paddle draft](../../tests/outside/breakout-pointer/checks/breakout-paddle-bounds.json)
- [Source derivation](../outside-trials/breakout-ci/derive-drafts.py) and [derived values](../outside-trials/breakout-ci/derivation.json)
- [Earlier trial](../outside-trials/breakout-ci/report.md)
- [Off-rail regression](../../tests/test_breakout_paddle_rail.py)
