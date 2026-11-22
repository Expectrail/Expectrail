# Breakout check review

Two of the four requested drafts are on main. The Ball draft still needs a failing replay of the post-launch defect it is meant to catch. The wall and paddle-contact checks have no final draft here. There is no approval request for this partial set. [Issue #716](https://github.com/Expectrail/Expectrail/issues/716)

## Paddle stays on its rail

After Start, the paddle drawing must stay inside the screen rectangle from (0, 606) to (360, 625) on every frame from 20 through 70. A passing run must also bring the paddle within 24 pixels of (170.4, 616) at tick 20 and (50.4, 616) at tick 70. The vertical band comes from the paddle's starting height and collision shape. The engine reports the rectangle of the drawing, including transparent pixels. This check cannot establish what was visible to the player or whether the Ball bounced. [Draft](../../../tests/outside/breakout-pointer/checks/breakout-paddle-bounds.json) · [Geometry measurements](../breakout-ci/public-control-feasibility.md)

| Engine diagnostic | Result in three runs |
|---|---|
| Unchanged route | Passed all 51 frames each time. [Fresh runs](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7069986164) |
| Comment-only change | Passed all 51 frames each time. [Hosted runs](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7068866421) |
| Paddle forced to x = 8 | Failed from frame 20, with the drawing 15.5 pixels past the left edge. [Hosted runs](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7068866421) |
| All route inputs removed, including Start | Needs-review each time. The engine observed all 51 frames, but the paddle missed a required position. [Fresh runs](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7069986164) |

## Ball launches and moves down

From frames 40 through 50, the entire Ball drawing must stay below y = 204. A pass requires all 11 frames, the two paddle positions above, and at least 8 world pixels of downward Ball movement between ticks 40 and 50. These measurements cover the opening of this route. Later wall crossings and paddle contacts fall outside that claim. [Draft](../../../tests/outside/breakout-pointer/checks/breakout-ball-starts.json)

| Engine diagnostic | Result in three runs |
|---|---|
| Unchanged route | Passed all 11 frames each time. [Fresh runs](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7069986164) |
| Comment-only change | Passed all 11 frames each time. [Hosted runs](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7068866421) |
| All route inputs removed, including Start | Failed at frame 40, 8 pixels past the boundary. All 11 frames violated it in each run. [Fresh runs](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7069986164) |
| Ball stopped after launch, paddle still moving | Needs-review each time. The engine measured 0 of the required 8 pixels. This produced zero assertion failures in three runs. [Hosted runs](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7068866421) |

Removing every input tests a game that never receives the Start click. It supplies no failing post-launch example. The fresh November 21 controls used headless Godot 4.6.3, the pinned public Breakout game, and the same seed for all six replays. The three traces agreed byte for byte within each case. These are engine diagnostics with no captured images or vision verdict. The run log includes the exact pin, both trace digests and the reproduction commands. [Run log](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7069986164)

In each stopped-after-launch run the engine recorded the same Ball from tick 40 through tick 50. Its measured movement over that window was zero. Removing a drawing or replacing the Ball instance in a copy of a clean trace instead made the movement unknown. Both outcomes give needs-review because this draft uses movement as a coverage condition. A Ball held still through tick 49 that caught up at tick 50 passed the trace control. The draft measures the difference between the endpoints and can miss a pause between them. [Checkpoint results and trace controls](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7070280022)

### Where to look when the Ball stops after launch

| Frame or tick | What the reviewer can check |
|---|---|
| 29 → 30 | At tick 29 the Ball centre was at world y = 302.867 in both recordings. At tick 30 it reached 309.296 on clean and stayed at 302.867 on the stopped copy. Frame 30 was the first differing image digest in all three paired runs. The retained digests locate that frame without showing which pixels changed. [Paired measurements](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7071628064) |
| 40 → 50 | The clean Ball centre moved from y = 373.588 to 437.879, a gain of 64.291 world pixels. All three hosted stopped runs report 0 against the required 8 and identify the same trace digest (prefix `9a16dcf3cb4a`). Tick 50 supplies the second measurement. [Clean trace](../breakout-ci/traces/breakout/draft-diagnostics/pointer-auto/trace.json) · [Hosted artifact 1](https://github.com/Expectrail/Expectrail/actions/runs/44915906724/artifacts/14712375580) · [Artifact 2](https://github.com/Expectrail/Expectrail/actions/runs/44918021456/artifacts/14711724532) · [Artifact 3](https://github.com/Expectrail/Expectrail/actions/runs/44924775195/artifacts/14715143603) |
| 70 | The second required Paddle position is read here. With the trace truncated at tick 69, the advisory experiment still needed review. At tick 70 it could identify a measured shortfall in all three stopped runs. The shipped draft returned **needs-review** in each hosted job. [Truncation experiment](https://github.com/Expectrail/Expectrail/issues/716#issuecomment-7071628064) |

## Sean's approval step

Once the four-check review is complete, Sean can approve each file whose exact contents he accepts. These are the commands for the two existing drafts. Editing the file's assertion, window or coverage afterward requires a new approval. [Content-binding rules](../../ci-gate.md)

```sh
python3 -m expectrail.spec_writer approve tests/outside/breakout-pointer/checks/breakout-paddle-bounds.json --by sean
python3 -m expectrail.spec_writer approve tests/outside/breakout-pointer/checks/breakout-ball-starts.json --by sean
```
