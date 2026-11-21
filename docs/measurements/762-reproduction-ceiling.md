# The reproduction ceiling, by hand (#762)

Measured November 21, 2026, by builder two, on Godot 4.7.2 on a local machine. No model was called and
nothing was dispatched or spent. The rows are [`bench/jit/ceiling/rows.json`](../../bench/jit/ceiling/rows.json),
written by [`tools/reproduction_ceiling.py`](../../tools/reproduction_ceiling.py); the table below is
kept equal to them by `tests/test_reproduction_ceiling.py`.

**Result.** For `slow-left` and `slides-after-stop`, the limit is **the generator**. One check per defect,
written from the report alone in the first round, passes the clean game 3/3, fails the defect 3/3, fails
the do-nothing control 3/3 (a real failure each time, not "cannot tell") and passes the comment-only edit
3/3. Each uses only the offered signal `player_dx_px` and two new probes. For `air-jump`, the limit is
**the check language**: no single check in it can state the obligation and survive the control. The two
halves of the obligation, judged together on the same runs, pass all four tests. Judged one at a time,
as the keep rule judges them today, neither is kept.

## How the checks were written

- **What I used.** For each defect: the report, the game's mechanics profile, the probe library, and the
  clean game's signal values, which I measured myself. I did not open `defect.patch` or
  `bugs/reported/air-jump.patch`. I did not open anything under `bench/jit/recordings/`, or the stand-in and
  rehearsal proposals written for these defects. The patches reached the engine only through the harness,
  and the tool reads only their SHA-256.
- **What I saw that I should name.** The public bench's README, which I opened to learn the bench's layout,
  has a table of how much each signal moved on each defect build. For these three defects it says:
  - `slow-left`: `player_dx_px` 225 to 337.5;
  - `slides-after-stop`: `player_dx_px` 200.01 to 784.67;
  - `air-jump`: `air_jumps` 1 to 7 and `max_rise_px` 113.61 to 424.49.

  I set each bound from the clean game's values and the report's own words ("about half speed", "almost
  straight away", the profile's double jump), not from those numbers. I cannot prove they had no
  influence. The generator itself is given more than this: each library probe's signal values on the bug
  build, in its prompt.
- **Committed before any replay of a defect.** The first-round answers went into commit `0c28a52` before
  anything was replayed on a defect build.
- **Turned into checks by the generator's own code.** Each answer is in the generator's planner format.
  The tool passes it to `intent.spark_intent` through a transport that returns the hand answer, then to
  `intent.propose_to_file`. The setting is the newest one, `signals-reach-evidence-menu-control`, with the
  candidate withheld. So the same parser, closed language and offer apply as for a model's answer. Nothing
  was refused and no diagnostic was raised.
- **One round each.** No defect used a revision round (below, for `air-jump`).

## The four tests

Each check was replayed three times on each of four builds, and every run was judged by the generator's
own `run._evaluate`:

| Build | What it is |
| --- | --- |
| clean | `game/platformer` |
| defect | the clean game plus the defect's patch |
| do-nothing control | the clean game with the check's actor frozen (`expectrail/jit/do_nothing.py`), judged by `do_nothing.judge`, which says "cannot tell" when a frozen player's floor state would decide the verdict |
| harmless | the clean game plus the registered comment-only edit (`agents/fixtures/operators/comment-only.patch`) |

The three runs of every route on every build were byte-identical traces (28 groups). Bubblewrap is not
installed on this machine, so every replay ran without isolation, on the public bundled game only.
The full run was made twice and gave the same table and byte-identical proposals.

**Clearance** is by how much the clean runs clear the check's bound at their tightest. **Defect margin** is
the same quantity on the defect build: negative means it fails by that much.

<!-- ceiling-table:start -->
| Defect | Round | Check | Clean | Defect | Do-nothing control | Harmless edit | Clearance (clean) | Defect margin | Kept as a reproduction |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `slow-left` | 1 | `jit-c1` lt `player_dx_px` | pass 3/3 | fail 3/3 | fails (fail 3/3) | pass | 62.5 px | -62.5 px | yes |
| `slides-after-stop` | 1 | `jit-c1` lt `player_dx_px` | pass 3/3 | fail 3/3 | fails (fail 3/3) | pass | 75 px | -86.01 px | yes |
| `air-jump` | 1 | `jit-c1` gt `max_rise_px` | pass 3/3 | pass 3/3 | fails (fail 3/3) | pass | 28.53 px | 28.53 px | no: does not fail the defect 3/3 |
| `air-jump` | 1 | `jit-c2` lte `max_rise_px` | pass 3/3 | fail 3/3 | passes (pass 3/3) | pass | 26.85 px | -284.03 px | no: passes the do-nothing control |
| `air-jump` | 1 | both, judged together | pass 3/3 | fail 3/3 | fails (fail 3/3) | pass | | | yes, if one check could say both |
<!-- ceiling-table:end -->

**The pipeline agrees.** Each first-round proposal was also replayed by the generator's own job:
`python -m expectrail.jit.cli run --withhold-candidate --offer signals-reach-evidence-menu-control`, with
the defect as `--base` and `bench/jit/public/no-fix.patch` as the candidate, as a `repro` dispatch runs
it. The records are committed beside the answers (`pipeline-round1.jit-run.json`):

| Defect | Valid | Catches | What the job said |
| --- | --- | --- | --- |
| `slow-left` | 1 of 1 | 1 strong | do-nothing control: fails |
| `slides-after-stop` | 1 of 1 | 1 strong | do-nothing control: fails |
| `air-jump` | 0 of 2 | none | `jit-c1` killed no near miss (the bug build is its only one); `jit-c2` passed the do-nothing control |

Each record's spend line shows the job's assumed price for a model call ($0.12) that did not happen,
because the proposal was replayed from a file.

## Per defect

### `slow-left`: a directional magnitude asymmetry

*"The robot walks left much slower than it walks right. Going right feels normal, going back left is about
half speed."*

- **Obligation.** Walking left is about as fast as walking right.
  - After one second right, then one second left, the robot must have come back more than 187.5 px of
    the 300 px the second right took it.
  - On the clean game it comes back 250 px; turning round costs the rest.
  - At half speed it would come back about 125 px. 187.5 is the midpoint.
- **Check.** `player_dx_px(right-left-1s) + 187.5 < player_dx_px(right-1s)`, a strict `lt` relation between
  two new probes: hold right 120 ticks then stand 60; hold right 120, hold left 120, then stand 60.
- **Why a strict relation.** `player_dx_px` is signed, and a relation compares one signal across two probes,
  so "left equals right" cannot be written as an equality of two walks. The return trip turns the
  asymmetry into one number. A still robot reads 0 on both probes, and `0 + 187.5 < 0` is false, so the
  control fails it.
- **Round.** 1.
- **Limit: the generator.** #755 found that the baseline wrote only equality relations for this defect
  (5 `holds-when-equal`, 0 demanding checks). The language and the offered signal were enough.

### `slides-after-stop`: a decay after release

*"When I let go of the arrow key the robot keeps sliding for ages before it stops, like the floor is ice.
It used to stop almost straight away."*

- **Obligation.** When the key is let go, the robot stops almost at once.
  - Walking right for half a second and then standing for a full second must leave the robot more than
    75 px short of where a whole second of walking takes it.
  - On the clean game it is 150 px short: it stops within a tick of release.
  - 75 px is half of what half a second of walking covers.
- **Check.** `player_dx_px(walk-let-go) + 75 < player_dx_px(walk-on)`. The probes are: hold right 60 ticks
  then stand 120; hold right 120 then stand 1.
- **Why a strict relation.** The bound alone ("the robot moves at most 75 px after release") is passed by a
  robot that never moves. Comparing against walking on makes the clean game demonstrate the movement the
  bound is about.
- **Round.** 1.
- **Limit: the generator,** for the same reason as `slow-left`.

### `air-jump`: a bound on an event count

*"Infinite jump while in the air."*

- **Obligation.** The player can jump once more in the air (the profile's `player.jump` claim), and no
  more. It has two parts, and both are required:
  - **Demand** (`jit-c1`). A second press in the air lifts the player more than 27 px higher than one
    press: `max_rise_px(jump-l40-x2) > max_rise_px(jump-l40-x1) + 27`.
  - **Bound** (`jit-c2`). Eight presses lift the player no more than 27 px higher than two:
    `max_rise_px(jump-l40-x8) <= max_rise_px(jump-l40-x2) + 27`.
  - Both use library probes where nothing is overhead.
- **Round.** 1. No revision was written. The revision the generator would send, captured from
  `intent.revise_to_file` with the first round's record, says only that `jit-c1` "did-not-fail-on-bug-build"
  and `jit-c2` was "passed-with-the-actor-doing-nothing", with their clean outcomes. That is what the table
  already shows. A revision cannot help, because no single check in the language can do the job:
  - **Why no single check exists.** A check survives the control only if its comparator is strict (`gt`,
    `lt`) or it demands activity (`min_event_count`, `min_motion_extent`, `event_response`). The activity
    demands are about projectiles or plain motion and cannot speak about jumps. A strict relation needs two
    probes whose clean values differ in the direction the bug reverses.
  - **What the bug does to the signals.** It only raises the jump signals (`max_rise_px`, `air_jumps`,
    `airborne_ticks`), and only on probes with three or more presses in one stretch off the floor.
  - **What the clean game allows.** On the clean game, no probe rises above the double-jump height and no
    probe makes more than one jump in the air. So there is no clean reference above the bound for the bug
    to cross.
  - **The rejected way round.** A check made from an accident of timing, such as comparing total airborne
    time against some unrelated probe, would have its threshold set from the bug build's numbers. That is
    fitting the check to the defect, which this issue forbids.
- **Judged together.** On the same runs, the two checks pass the clean game 3/3 and fail the defect 3/3
  (the bound fails). They fail the control 3/3 (the demand fails) and pass the harmless edit 3/3.
- **Limit: the signals, in the sense the issue gives it.** The trace has the signal: `max_rise_px`
  separates the builds by 284 px beyond the bound. What the language lacks is a way to state one
  obligation with two clauses. Today's keep rule judges each check alone, so the control drops the bound,
  and the demand alone never fails on the bug. This confirms the issue's hypothesis for `air-jump`.

`enemy-ledge` was left out, as the issue asks. It was not attempted.

## What the ceiling is, and what to change first

On these three public defects, hand-written checks reproduce three of three under the do-nothing rule.
For two of them, that took one check in today's language, so the gap between them and the baseline's 0 of
those two lies in how the generator is asked:

- The baseline wrote equality relations.
- A working check needs a strict relation with a tolerance taken from the clean game.
- It also needs a probe pair built so that the clean game shows a known difference and the bug closes it:
  out and back for an asymmetry, walk on against let go for a decay.

The third needs a compound check, which the language does not have. **What I would change first:**

1. **The generator.** Run the `signals-reach-evidence-menu-control` setting (#757), which already tells the
   proposer that `gt`/`lt` survive the control. Measure whether it finds strict relations like these
   before changing more text.
2. **Then the language, for bound-shaped defects.** Add a check made of a demand and a bound, judged
   together on the same runs, with the do-nothing control applied to the pair. Every "too much" defect
   (too high, too often, too fast) has the shape `air-jump` has. This is a schema change and is filed as its
   own issue, not made here.

This is three public defects, not a rate. It says what one person with the generator's tools reached, not
what a model will reach.

## Reproduce

```
./harness/get_godot.sh && export PATH="$PWD/tools/godot:$PATH"
python3 tools/reproduction_ceiling.py --work NEW_FOLDER --rows bench/jit/ceiling/rows.json
python3 -m expectrail.jit.cli run --report-file bench/jit/public/slow-left/report.txt \
    --candidate bench/jit/public/no-fix.patch --base bench/jit/public/slow-left/defect.patch \
    --proposal bench/jit/ceiling/slow-left/round1.proposal.json --out NEW_FOLDER2 \
    --withhold-candidate --offer signals-reach-evidence-menu-control
```
