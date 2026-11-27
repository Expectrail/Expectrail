# One approval sitting, before blind set 4 is sealed

Blind set 4 (#281) is sealed on December 4 for a run on December 5 to 7. A draft cannot clear or
reject a change, so every candidate judged only by drafts returns neither accept nor reject. This
page gathers every draft that is ready for approval today, with the control evidence behind each,
so the sitting happens once rather than per project.

Approval binds to a file's exact contents (`docs/ci-gate.md`). Editing an assertion, window or
coverage afterwards requires a new approval. No agent may write an `approval` field.

## What the sitting changes

Four Godot checks are approved today: `player-always-visible`, `coins-visible`,
`player-stays-above-ground` and `dodge-play-area`. Between them they reach four of the ten defect
families #282 requires. Six families have nothing that can reject a defect.

Approving the five checks below reaches **four of those six families**, taking family coverage from
four of ten to eight of ten. The remaining two cannot be approved at all yet, because the gate has
no assertion that can express them; they are engineering, not judgement. See "Not approval" below.

## Ready: five checks

Every arm below was run three times on a public route with the same bindings and window. "Decisive
fail" means the check rejected with a complete judged window, not that it ran out of evidence.

| # | Check | Family | Clean | Public defect | Do-nothing | Harmless edit |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | [`player-reaches-opening-coin`](../specs/drafts/727/player-reaches-opening-coin.json) | Movement and input | 3/3 pass | Wrong direction, 3/3 fail | Frozen player, **3/3 decisive fail** | Comment-only, 3/3 pass |
| 2 | [`middle-enemy-on-return`](../specs/drafts/727/enemy-patrol/checks/middle-enemy-on-return.json) | Spawning and enemy behaviour | 3/3 pass | Fast left, **3/3 decisive fail** | Frozen at spawn, **3/3 decisive fail** | Comment-only, 3/3 pass |
| 3 | [`player-stays-in-viewport`](../specs/drafts/727/camera-viewport/checks/player-stays-in-viewport.json) | Camera and viewport | 3/3 pass, 63/63 frames | Right-limit crop, **3/3 decisive fail** | Fixed camera, **3/3 decisive fail** | Comment-only, 3/3 pass |
| 4 | [`pause-menu-score-after-five-pickups`](../specs/drafts/727/exact-score/checks/pause-menu-score-after-five-pickups.json) | State, score and counters | 3/3 pass, read 5 | Double count, 3/3 decisive fail, read 10; stuck counter, 3/3 decisive fail, read 0 | Frozen player, 3/3 needs-review, `not_exercised` | Comment-only, 3/3 pass, read 5 |
| 5 | [`breakout-paddle-bounds`](../tests/outside/breakout-pointer/checks/breakout-paddle-bounds.json) | Positional bounds, on Breakout | 51/51 pass each run | Paddle forced to x=8, failed from frame 20, 15.5 px past the left edge | Every input removed, needs-review at a missed required position | Comment-only, 51/51 pass each run |

Measurements: [opening walk](measurements/727-opening-walk.md) ·
[middle enemy](measurements/727-middle-enemy.md) · [camera viewport](measurements/727-camera-viewport.md) ·
[exact score](measurements/744-exact-score.md) ·
[Breakout review](outside-trials/breakout-pointer/checks-for-approval.md) ·
[family map](measurements/721-family-coverage.md)

### What each one does not claim

Read these before approving. Each is a measured limit, not a worry.

1. **Movement**: direction and arrival only, not speed. Half speed still reached the coin and passed 3/3.
2. **Enemy**: presence and location during the return window. An enemy frozen *inside* the region passed 3/3, and so did a run with the upper enemy missing.
3. **Viewport**: drawing-box containment on the rightward traversal. The decisive margins are thin, 1.751 px at frame 119 and 0.951 px at frame 77. High-platform framing and rendered pixels need their own evidence.
4. **Score**: one bound Label read at route completion, after an independent count of recorded pickups. A route with no pickups is `not_exercised`, which is silence rather than a pass.
5. **Breakout paddle**: the rail from (0, 606) to (360, 625), frames 20 through 70. It says nothing about what the player saw or whether the Ball bounced.

## Hold: one check

[`breakout-ball-starts`](../tests/outside/breakout-pointer/checks/breakout-ball-starts.json) is not
recommended for approval in this sitting.

It rejects exactly one thing: a game that never receives the Start click. For the defect it is named
for — the Ball stopping after launch — it returns **needs-review in all three runs**, because the
required downward movement is a coverage condition rather than an assertion, so a dead Ball produces
silence instead of judgement. It also measures only the endpoints at ticks 40 and 50, so a Ball that
pauses and catches up passes.

Approving it would add a coverage witness, not a detector. Either hold it until the movement
requirement becomes an assertion, or approve it knowing it is a witness; it should not be counted
towards family coverage either way.

## Not ready: one check

[`system-override/ship-visible`](../tests/outside/system-override/checks/ship-visible.json) has no
control run behind it. Its coverage is `minFrames: 150` with no `reached` witness, so nothing
establishes that the route exercised the ship: a ship that is visible and never moves passes. The
draft validation log for that trial ends in
`expectrail.project_config.ProjectConfigError: system-override: no such file`
([log](outside-trials/system-override/evidence/28-validate-drafts.log)).

It needs the same four arms as the five above before it can be judged.

## Not approval: two families

These two are blocked on the gate's assertion vocabulary, so no sitting can cover them.

- **Timing and cooldowns.** The evidence is complete — long cooldown 3/3 trace fail, never-made projectile 3/3 trace fail, clean and comment-only 3/3 trace pass — but the gate has no shot-count or interval assertion, so there is no draft to approve. [Measurement](measurements/727-cooldown.md)
- **HUD and text.** The gate has no rendered-text assertion, and both configured pixel observers refuse the counter's text role. The rendered-text arms were unrun. [Finding](measurements/727-hud-text.md)

## One cleanup first

`tests/outside/breakout/checks/` holds older, coarser files under the **same two check ids** as the
reviewed ones: the paddle region is the whole viewport `[0, 0, 360, 640]` rather than the rail, and
the Ball boundary is `y=300` rather than `204`. `tests/outside/projects.json` points the registered
`breakout` project's `config`, `routes` and `draftSpecs` at `tests/outside/breakout-pointer/`, and
borrows only `tests/outside/breakout/changes/*.patch`, so nothing loads the coarse checks today.

They should still go before the sitting. Approving one file per id while an unapproved file with the
same id sits in the tree invites a later route or glob to pick the wrong one.

## The commands

In this order, after the cleanup above. Each writes an `approval` bound to that file's exact bytes.

`--by` is stored verbatim and nothing validates it. Every approval in the repository today reads
`Sean Keluo-Udeke`, so these commands use that string: a second approver identity would make the
audit trail harder to read, in the one field of this repository that records a human decision (#749).

```sh
python3 -m expectrail.spec_writer approve specs/drafts/727/player-reaches-opening-coin.json --by "Sean Keluo-Udeke"
python3 -m expectrail.spec_writer approve specs/drafts/727/enemy-patrol/checks/middle-enemy-on-return.json --by "Sean Keluo-Udeke"
python3 -m expectrail.spec_writer approve specs/drafts/727/camera-viewport/checks/player-stays-in-viewport.json --by "Sean Keluo-Udeke"
python3 -m expectrail.spec_writer approve specs/drafts/727/exact-score/checks/pause-menu-score-after-five-pickups.json --by "Sean Keluo-Udeke"
python3 -m expectrail.spec_writer approve tests/outside/breakout-pointer/checks/breakout-paddle-bounds.json --by "Sean Keluo-Udeke"
```

## What this does not settle

Eight of ten families with a rejecting check is not a measured catch rate. None of these five has
been run against a defect written by anyone other than the team, which is what #263 and blind set 4
exist to establish. Approval makes them able to judge; it does not say how well they judge.
