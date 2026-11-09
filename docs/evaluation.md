# Evaluation plan

This plan identifies the cases and measurements behind the numbers in the video and README,
so someone else can rerun them.
Owner: Sean. Status: draft for the team to review by noon on Tuesday, October 27.

## The question the benchmark answers

Does Expectrail catch and fix visual regressions that a coding agent given screenshots would miss
or fix wrongly? Each case runs under three conditions with the same repair budget, and every
candidate fix is judged by the same independent verifier:

| Condition | What it gets |
| --- | --- |
| Existing checks | The game's own build passing; it has no tests, so every seeded bug passes this condition. This row shows the gap. |
| Muse Code with screenshots | The failing frames, the route, the logs and the instruction in plain English. No structured checks. |
| Expectrail | The same, plus structured test specs, SAM 3.1 observations and the evaluator's verdict. |

## Bug families (first wave)

Four families, matched with clean runs. A variant is a patch in `bugs/`
(seeded by Timo); the clean run is the same route with no patch.

| Family | Test specs | Development variants (in `bugs/`) | Held out |
| --- | --- | --- | --- |
| physics-fall-through | `specs/player-stays-above-ground.json` (never-crosses against the level's ground line: position log, plus SAM's robot box when SAM is on) and `specs/player-always-visible.json` (SAM) | v1 the player's collision mask drops the ground layer; v2 the ground tiles lose their collision layer | v5, v6 |
| sinking (added Oct 28) | `specs/player-stays-above-ground.json` | v1 the player's collision shape sits too high, so it rests inside the ground; v2 the sprite is drawn too low (only the SAM hybrid sees it) | v3, v4 |
| missing-texture | `specs/coins-visible.json` (visible in every frame, SAM) | v1 the coin texture points to a missing file and has lost its UID; v2 the coin texture is cleared | v5, v6 |
| layering | `specs/player-always-visible.json` (visible in every frame, SAM) | v1 the player's z index drops behind the level art; v2 the player's sprite gets a negative z index | v5, v6 |

The held-out variants and routes are described only in the private repository; their mechanisms
are not written down here. The first held-out variants of the three original families (v3 and v4)
were described in this file from Oct 26 to Oct 28, so they stay in git history; they are retired
from the benchmark and replaced by v5 and v6, written fresh on Oct 28 and never described here. SAM 3.1 does not see the ground in this game's art, which is why the
ground line comes from the level itself (docs/sam.md).

The playbook's original layering bug (the HUD drawn behind the background) does not fit this game:
its only HUD, the coin counter, is inside the pause menu and is not on screen during play. Text
overflow, softlock and motion jitter wait until after Gate 2.

**Held out** means two things, both kept in the private repository `seanudeke/Expectrail-heldout`
and never in this one:

- **Held-out variants** (the two active variants of each family in the table) are a
  generalization set. We build and tune Expectrail on v1 and v2 only; the held-out variants run
  once, in the benchmark, and their results are reported separately. They never appear in a repair
  request or on the fixer's machine before then. Detection on them (would the verifier reject a
  candidate that leaves the bug in place) is measured by the `heldout-bench` mode of the SAM probe
  workflow (`agents/heldout_bench.py`), which publishes only each variant's id and verdicts.
- **Held-out routes** guard each candidate fix. The verifier replays the seeded bug plus the
  candidate on routes the fixer has never seen, and requires the visual spec and the gameplay
  check to pass there too. A fix tuned to the smoke route (for example one that only works on its
  exact timing) fails here. The verifier reads the set from `EXPECTRAIL_HELDOUT_DIR`; CI fetches it
  with the `HELDOUT_TOKEN` secret and never uploads held-out frames or traces as artifacts. Without
  the set (offline runs, forks) the check falls back to an interim fixture, labeled
  `interim-fixture` in the verification's suite provenance.

**Clean controls:** each family's spec must pass on the clean route. A spec that fails a clean run
is a false alarm and counts against us, not a bug.

Detection on the held-out variants, ids and verdicts only, as the benchmark published them (run
41003749744, October 30; the record is `bench/detection/held-out.json`, per-check counts in
docs/sam.md):

| Held-out variant | Caught, SAM on | Caught, SAM off |
| --- | --- | --- |
| clean (control) | no false alarm | no false alarm |
| physics-fall-through/v5 | yes | yes |
| physics-fall-through/v6 | yes | yes |
| sinking/v3 | yes | yes |
| sinking/v4 | yes | yes |
| missing-texture/v5 | yes | no |
| missing-texture/v6 | yes | no |
| layering/v5 | yes | no |
| layering/v6 | yes | no |

With SAM on, 8 of 8 variants were caught; without it, 4 of 8; no false alarm on the clean routes
either way. The first full run (40805529944, October 28) caught 7 of 8 with SAM on and 3 of 8
without; the difference, sinking/v4, and the check built after that miss, are documented in
docs/sam.md ("The drawn floor").

## Reported bugs (added Oct 30)

The families above were seeded by the team. `bugs/reported/` holds the other kind: four
reproductions of publicly reported Godot bugs. Two were fixed by Godot contributors in this demo's
own history and two were reported in other developers' Godot games. We wrote the patches that put
them back; the bug, its symptom and its cause come from the cited reports
([bugs/reported/README.md](../bugs/reported/README.md)).

| Bug | Source | Route | Engine-record check |
| --- | --- | --- | --- |
| `air-jump` | this demo, commit cf98fed (2016) | `climb-gap` | `jump-height` |
| `gun-cooldown` | this demo, PR #686 (2022) | `tap-shoot` | `fire-rate` |
| `body-flip` | godot#78613 and forum reports | `turn-and-shoot` | `facing-follows-motion` |
| `enemy-ledge` | Godot forum | `wait-for-patrol` | `enemies-stay-up` |

`agents/reported_bench.py` (workflow **Reported bench**, on every pull request that touches it)
renders each bug and the clean game on the smoke route and the four reported routes, and judges
every replay with today's verifier checks (SAM off: the engine ground check and the gameplay
check) and with five engine-record checks (`agents/trace_checks.py`) that read the harness trace:
the robot's facing, the enemies and the bullets as well as the robot. Results:
[`bench/reported/`](../bench/reported/README.md).

How to read it:

- The engine-record checks were written after the bugs were reproduced, so this is a development
  result, not a held-out one. It shows the bugs are visible to Expectrail's engine record and that
  the rules raise no false alarm on the clean game; it does not show they would have been found
  blind. The verifier does not run these checks yet.
- The result that would count as blind is a natural catch: the checks and guards committed before
  Muse Code runs, the fixer given the reporter's own words, and a fix that looks right but breaks a
  guard rejected. `agents/reported_trial.py` runs it (the Fix matrix with set `reported`, SAM off):
  each bug five times, every candidate judged by Expectrail, by the bug's own public check and by
  Muse from screenshots. The guards live in the held-out set; their digest was committed in
  `bugs/reported/guards.sha256` before any trial ran, and a trial refuses any other guard file
  (protocol in [bugs/reported/README.md](../bugs/reported/README.md#running-a-natural-catch-trial),
  results in [`bench/reported/trial.md`](../bench/reported/trial.md)). The first run, on October 30,
  found none: Muse Code fixed all 20 cases on its first attempt, every candidate passed every
  check and guard, and Muse from screenshots rejected one that Expectrail accepted.

## Discovery: checks nobody wrote (added Oct 31)

Everything above judges with checks people wrote. Advisory discovery ([discovery.md](discovery.md))
is measured separately, because it answers a different question: does Expectrail find a defect
nobody wrote a check for? It never decides a fix, so it has no place in the fix matrix or the judge
benchmark.

- **Development reproduction** (recorded): one CI job per build, no healthy reference build, the
  clean game as the false-alarm control. The four reported bugs were found and the clean game
  raised nothing (run 41238187197, `bench/discovery/`). The profile was written after reading those
  four reports, so this counts as development evidence only. The eight seeded development variants
  are the builds it was not written for: two flagged, six missed.
- **Blind run** (recorded, run 41248745687): the discoverer's files are frozen
  (`discovery/freeze.json`), a fresh set of ten entries (8 defects, 2 intentional changes) was
  written after the freeze in the private repository, and its digest was committed in
  `bugs/fresh/fresh.sha256` before the run. It ran once, planner off, from a checkout that passed the
  freeze check, and published counts only: **4 of 8 defects flagged, 0 of 3 healthy builds (the two
  intentional changes and the clean game), no incomplete job**
  (`bench/discovery/blind-run-41248745687.json`). A second run with the Muse Spark planner on
  (41250932288) gave the same counts because the planner never answered (no content from any
  call), so the planner-on condition is not measured (`bench/discovery/blind-run-41250932288.json`).
  Set 1 is then retired: the planner's fix touches a frozen file, so fresh set 2 is written against
  freeze 2 and gets one planner-off and one planner-on run, scored the same way (runs 41319184209
  and 41319197682): **3 of 8 defects with the planner off, 4 of 8 with it on, 0 of 3 healthy
  builds either way.** Across both sets the frozen templates flagged 7 of 16 defects and none of
  the 4 intentional changes or the clean game.
- **What we report for discovery:** defects flagged out of defects; intentional changes and the
  clean game flagged (false alarms); findings that did not reproduce three times out of three;
  incomplete jobs. Development and blind results are reported apart, and a miss is never answered
  by changing the frozen system.

## Ground truth

The harness records the player's true position every tick (`trace.json`), so for the physics and
layering families we know what really happened without trusting a model:

- a fall-through is real when the player's y keeps rising past the ground's y (in the clean smoke
  route the player never goes below y = 640; with v1 it reaches y = 1922);
- every seeded variant is a known bug, and every clean run is a known non-bug.

That gives each verdict a label, so "defects caught" and "false alarms" are measured, not judged by
eye. The trace is the verifier's instrumentation: it is added at run time by the harness, outside
the patch the fixer writes.

## Gameplay checks (verifier side)

A fix must keep the game playable. On the smoke route, the clean game:

- moves the player about 485 units to the right (x from 90 to about 575);
- ends with the player standing on the floor;
- never puts the player below the ground.

A candidate that stops the fall by freezing the player, or by removing gravity, fails these and is
rejected even though the visual check passes. Taofeek's verifier implements them in
`agents.gameplay` from the harness/fixture `trace.json` (not SAM observations or an invented
goal). The verification check id is the opaque label `player-motion-on-smoke` (not a SAM
`reaches` assertion). Harness smoke uses `MIN_DELTA_X_HARNESS` (slack under the ~485 clean
measurement); offline fixtures use `MIN_DELTA_X_FIXTURE`. Same predicate for both.

## How the fix matrix runs

`agents/matrix.py`, run by hand through the **Fix matrix** workflow, takes each development
variant under each condition. Both conditions get the same files: five screenshots of the bugged
run at fixed frames (0, 30, 60, 90, 119, never chosen by a verdict), the route and the run's log,
the same three attempts and the same editable globs (`player/**`, `level/**` and
`game_singleplayer.tscn`, since layering v1 lives in the game scene). The screenshots condition
gets the expected behaviour in plain English and, after a rejected attempt, only that it did not
work. The Expectrail condition also gets the repair request (spec, verdict, evidence) and the
verifier's reasons, and opens a repair only when its own check caught the bug. Every candidate is
judged by the same verifier with SAM on and the private routes mounted; Muse Code runs only inside
bubblewrap there. "Existing checks" needs no run: the game has no tests, so it catches nothing.

A third condition, `escalate` (added October 30), is what the overnight loop now does
([report-first.md](report-first.md)). The first attempt gets the screenshots briefing. Only after
the verifier rejects an attempt does the next one get the Expectrail briefing, with the verifier's
reasons limited to the public checks. The workflow runs it by default beside the other two, so
every matrix run measures the policy the loop ships.

The held-out variants go through the same matrix once, after the code freeze (`set: held-out`).
Only ids, outcomes and per-attempt decisions leave the runner for them: a candidate patch, a
verifier reason or Muse's log would describe the private bug.

## Who accepts a fix that only looks right (judge benchmark)

The fix matrix showed both conditions fix all 8 development variants, so the fix rate does not
separate them. What Expectrail is for is the judgement: would it ship a fix that only looks right?
`agents/judge_bench.py` puts 15 candidates, each with a known right answer, in front of three
judges. The 8 good candidates undo each development bug exactly. The 7 bad candidates
(`agents/fixtures/`) look fixed and are not. Five sit on fall-through v1: the fall stops but the
robot is drawn behind the level art or inside the ground; the floor's collision is moved below its
art; the robot can no longer move; or only a comment changes. The sixth pushes the sinking fix so far
the robot floats, and the seventh "fixes" layering by deleting every tree. The judges are the verifier with SAM
on, the verifier with SAM off, and Muse judging from five before and five after screenshots plus
the player's one-line report, inside bubblewrap. Results and both runs are in `bench/judge/`.

Twice, live (runs 40936362830 and 40943391994):

| Judge | Good fixes accepted | Bad fixes accepted |
| --- | --- | --- |
| Expectrail, SAM on | 8 of 8, both runs | 0 of 7, both runs |
| Expectrail, SAM off | 8 of 8, both runs | 3 of 7, both runs |
| Muse from screenshots | 6 of 8, then 7 of 8 | 2 of 7, both runs |

A third run on October 31 ([41230177124](https://github.com/seanudeke/Expectrail/actions/runs/41230177124),
`bench/judge/glimmer/`) gave these three judges the same counts, Muse from screenshots at 6 of 8 as in
the first, and added a fourth judge: the verifier with Muse Glimmer checked against the engine and no
SAM. It accepted 8 of 8 good and 0 of 7 bad, but the deleted trees got past every public check under
Glimmer and were stopped only on a held-out route ([docs/open-weights.md](open-weights.md)).

On November 1 the same 15 candidates went to the strongest models two other vendors sell, as
screenshot judges beside Muse in one run ([41320444374](https://github.com/seanudeke/Expectrail/actions/runs/41320444374),
`bench/judge/outside-models/`, `agents/outside_judge.py`). Each got the screenshot judge's prompt
byte for byte, the same ten frames under the same file names, and the same decision line, three
times, each pass its own request. The models, prompt, passes and scoring were fixed before the run,
and it was not run again. The SAM-on verifier was skipped; its decisions are the three runs above.

| Judge, from screenshots | Good fixes accepted, per pass | Bad fixes accepted, per pass |
| --- | --- | --- |
| Claude Fable 5.1 (`claude-fable-5-1`) | 6, 6 and 7 of 8 | 0, 0 and 0 of 7 |
| GPT-6 Astra (`gpt-6-astra`, reasoning effort high) | 8, 7 and 8 of 8 | 0, 0 and 0 of 7 |
| Muse Code, the same frames, the same run | 7 of 8 | 2 of 7 |

- Both caught the two fixes Muse accepted. They saw the robot's feet below the grass line, and the
  enemies sunk into the floor when the floor's collision was lowered: the five frames do show it.
- Their mistakes were on correct fixes. Claude rejected sinking/v1 in all three passes and
  sinking/v2 in two, GPT sinking/v2 once, each reading the robot as floating above the ground, as
  Muse does. Those fixes are exact undos, so what they saw is how the clean game plays.
  Claude's third pass on the hidden player was needs-review, not an accept.
- Expectrail with SAM made no mistakes on either, in three runs. On 15 cases the difference from
  GPT is one judgment; it says screenshot judging errs even in a simple game, not how often it would
  in a bigger one. About $21 at list prices for the 90 outside-model requests.

What the reasons show (second run):

- Without SAM the verifier sees the engine, not the picture, so it passes the hidden player, the
  sunk player and the hidden trees. SAM's checks reject all three.
- Muse accepts the lowered floor and the sunk player ("player stays in view, on ground"). The five
  frames do show the feet below the grass line: Claude and GPT, given the same frames, saw it (see
  above). It rejects real sinking fixes because it reads a normal jump as the robot floating.
- The floating robot fails `player-stays-above-ground` in both modes: the spec holds the feet within
  20 px of the ground, so floating fails as well as sinking.
- Expectrail does not notice the missing trees. It rejects that candidate because the player is
  still drawn at z_index -3, behind the grass, bushes and tiles, so `player-always-visible` fails.
  Muse rejects it because the trees are gone. Deleting scenery that no spec covers would pass.

Limits: the bad candidates were written by us, and three of them (hide, sink, lower the floor) are
cases the verifier was built to reject, so 0 of 7 shows it holds on known tricks, not on new ones.
Fifteen cases is small. The judges do not see the same evidence: that is the comparison we claim
(what each would accept from what it is given), not an equal-information test.

## Mutation bench (added Nov 1)

The judge benchmark's bad fixes were written by us. In the mutation bench, Part 2's bugs come from a
seeded generator, and Part 1's wrong fixes from six operators the team wrote but did not aim at any
case. It was registered before any case in the study was judged: the generator, its operators, the seed, a stratified
sample of 150, the steps, an oracle that calls a change visible if it differs from the clean game in
the engine's record or in any frame (thresholds 0 and 0), and the stop rule
([`bench/mutation/preregistration.json`](../bench/mutation/preregistration.json)). Only public checks
decide. The registration pins the code that judged the runs, and a test fails any pull request that
changes a pinned file.

| Part | Cases | Result | Run |
| --- | --- | --- | --- |
| 1, wrong fixes | 47 made by six operators: 39 wrong, and 8 right (a correct fix plus a comment) | **31 of 39** wrong fixes caught, 24 only with SAM; all 8 right ones accepted. The 8 misses are one operator, `scale-to-zero`, that changes nothing in the running game | [41268021760](https://github.com/seanudeke/Expectrail/actions/runs/41268021760) |
| 2, generated bugs | 150 single edits sampled, 77 different from the clean game | Weighted score **0.9%**, because none of the 45 numeric edits was caught; over the sample as drawn, 10 of 77 (5 by the cheap tier, 5 only with SAM). Of the 45, 44 move, resize or re-layer scenery no check covers, one draws the player's sprite 26 px off its body | [41268023631](https://github.com/seanudeke/Expectrail/actions/runs/41268023631), [41323827584](https://github.com/seanudeke/Expectrail/actions/runs/41323827584), [41323829361](https://github.com/seanudeke/Expectrail/actions/runs/41323829361) |
| 3, AI-written fixes | Muse Code on the 10 bugs Part 2 caught | 10 fixed on the first attempt, all accepted, all correct on six routes, five of which the judge does not use: **0 natural catches**. They were bugs the checks had already caught, reported in the catching check's words. Muse from screenshots rejected 5 of the same 10 | [41330361829](https://github.com/seanudeke/Expectrail/actions/runs/41330361829) |

What it adds to the plan above: Expectrail catches what its checks name, and the bench measures how
much of a game that is. Most of what a random edit changes is scenery no check names. The cheap tier
and SAM catch different things (they agreed on none of the 12 cheap catches checked), so SAM cannot
stand in for the cheap tier. The limits, including who ran what and the agreement sample of 5 against
the registered 20, are in [the bench's write-up](../bench/mutation/README.md#limits-of-these-results).

## What we report

For each condition, across all variants and clean runs:

- defects detected out of defects tested;
- false alarms out of clean runs;
- fixes accepted by the verifier out of fixes attempted, and accepted fixes that broke something else;
- unresolved cases and why;
- wall-clock time, model calls, and total cost (API spend and compute).

Rules: report frames analyzed, not frames captured; repeated runs of the same variant are not
separate bugs; held-out results are reported separately from development results, reported
bugs separately from seeded ones, and discovery's advisory findings separately from the verifier's
decisions; every number on
screen comes from `bench/` and reruns with one command.

Rerun a result on the code that produced it: the hackathon submission is commit `c169a5e`, tagged
`submission`, and each run page shows the commit that run used. The mutation bench's workflows
check out the tag for judged runs, because its pre-registration describes the code there. Live
Muse and SAM calls do not reproduce bit for bit.

## Budget

Sixteen variants (eight development, eight held out, across four families) and their clean runs,
three conditions, up to three repair attempts each. Each run renders 120 frames; SAM 3.1 sees a
sample: every fourth frame by default (`EXPECTRAIL_SAM_EVERY`), refined to the exact frame when a
sample fails, and every remaining frame confirmed before a pass, so a pass still rests on all 120.
Decided October 28, after the first live measurements.
