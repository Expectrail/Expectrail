# Check that the Breakout ball moved after launch

## What changed

The previous Ball draft could pass when the ball crossed the launch boundary and stopped. Its two movement checkpoints watched the paddle. An existing test replay reproduced the problem with a stationary Ball and a moving Paddle.

The revised draft requires the centre of the same visible Ball drawing to move down at least 8 world pixels between ticks 40 and 50. Start is released at tick 14. Both the physics and capture rates are 60 Hz. Eight pixels is one collision diameter in the pinned scene. The level-one ball launches downwards at 400 px/s at a random angle within 45 degrees of vertical. This small minimum allows different launch angles and horizontal positions. A slower ball can still pass. A game redesigned to pause the ball in this window would need a different obligation. [Pinned game and derived values](../outside-trials/breakout-ci/derivation.json)

The checkpoint follows the recorder’s role and instance ID at every tick in the interval. The world-coordinate bounds must come from a visible drawing, and the two endpoint rectangles must have the same size. Missing ticks, a replacement instance, ambiguous drawings and incomparable geometry produce insufficient observation. A stationary drawing leaves the checkpoint unreached. Both outcomes give the draft `needs-review` when the visual assertion otherwise passes. An animated drawing can move on a stationary body. The Ball on this game pin uses static art.

This change uses the existing coverage evaluator and review page. The Ball spec is a draft. A legacy approval without a content digest cannot authorize a new role-displacement checkpoint. The existing gate checks a human approval against the exact spec content.

## What was run

The [public trial registry](../../tests/outside/projects.json) includes a game-level [stationary-Ball control](../../tests/outside/breakout/changes/stationary-ball.patch). It stops the Ball once its y position reaches 300, after the launch clears the original boundary. The two paddle checkpoints, all eleven judged frames and the y=204 boundary still apply.

Twelve rendered diagnostic replays ran at upstream `0ac7aed`, three per row. Godot 4.6.3 used Xvfb and Mesa llvmpipe. Each replay recorded 407 frames. Local Bubblewrap could not set up its uid map, so the local measurements use diagnostic execution.

| Version | World y at tick 40 → 50 | Previous Ball draft | Revised Ball draft | Paddle draft |
| --- | --- | --- | --- | --- |
| Pinned game | 373.588 → 437.879 | pass | pass | pass |
| Harmless comment | 373.588 → 437.879 | pass | pass | pass |
| Paddle escape | 373.588 → 437.879 | needs-review | needs-review | fail |
| Stationary Ball | 302.867 → 302.867 | pass | needs-review | pass |

On the stationary version the paddle moved from x=170.702 at tick 20 to x=49.767 at tick 70. The earlier Ball draft passed on that same replay. All three stationary traces had SHA-256 prefix `9a16dcf3cb4a`. The declared checkpoint lets the reviewer see which drawing, coordinates and ticks have to support the obligation.

To reproduce all four registered cases from the public pin:

```sh
python3 -m tools.outside_trial --fetch --only breakout --execution-class diagnostic --out runs/breakout-movement
```

The [generator](../outside-trials/breakout-ci/derive-drafts.py) reproduced both public drafts and their geometry record byte for byte. The focused tests cover the [shared checkpoint](../../tests/test_bound_role_movement.py) and the [public trial](../../tests/test_outside_root.py). A second local diagnostic run used the pinned Godot 4.7.2 binary and the full trial command. It matched all four registered cases. All four verification attempts stopped before creating jobs. The stationary-Ball finding names the missing movement: 0 world pixels down between ticks 40 and 50, with 8 required. These results describe engine diagnostics. The outside trial still refuses to launch verification with the unapproved specs. Paddle contact, wall bounces and an unaided developer session are separate evidence gaps.

## Files

- [Checkpoint contract](../../contracts/test-spec.schema.json), [evaluator](../../expectrail/coverage.py) and [review text](../../expectrail/onboard_review.py)
- [Public Ball draft](../../tests/outside/breakout-pointer/checks/breakout-ball-starts.json), [control patch](../../tests/outside/breakout/changes/stationary-ball.patch) and [pinned trial report](../outside-trials/breakout-ci/report.md)
