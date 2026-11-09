# Advisory discovery: checks nobody wrote

Built October 31, 2026. Expectrail replays generic probes on a build and judges each replay against
contracts read from the game's own code. It reports a finding only when the same failure occurs
three times out of three. Discovery cannot accept or reject a fix; the verifier and its checks
are unchanged.

## Two kinds of checks

Expectrail now runs two kinds of checks, and only one of them can reject a change:

| | Written by people | Discovered by Expectrail |
| --- | --- | --- |
| What | Three approved specs (the robot stays above the ground, the robot is visible, the coins are visible), the gameplay check, and the held-out bugs and routes. Five engine-record checks for the reported bugs, written after they were reproduced and run by the reported-bug bench and trial, not by the verifier | 22 generic probes, judged by contracts that twelve templates build from a profile of four claims read from the game's code (the double jump, the gun's cooldown, the sprite's facing, the enemies' patrol). Optionally, Muse Spark proposes more probes and contracts in the same closed language |
| Who writes them | Muse Spark drafts a spec from one sentence and a person approves it; teammates write the held-out cases | The templates, with no model; a planner's contracts carry `model_prior` authority and are never approved by being proposed |
| Effect | Gate: any failure rejects the change | Advisory: findings are reported beside the decision and never change it |
| Shown so far | 8 of 8 held-out bugs caught with SAM; 0 of 7 fixes that only look right accepted | 4 of 4 reported bugs found, no false alarm on the clean game (development reproduction); 2 of the 8 development bugs it was not written for |

The approved checks caught none of the four reported bugs ([`bench/reported/`](../bench/reported/README.md)).
This is the first slice of the answer: the advisory part of the team's autonomous-discovery
specification (its "restricted competition slice"), built on public material only. What comes after
it is in [What's next](#whats-next).

## Status, October 31

- **Built and measured:** everything on this page, locally and in CI (below).
- **Tested blind on two fresh sets:** each written after a freeze, by a session that never saw the
  discoverer's rules, with its digest committed before any run. With the planner off, the frozen
  templates flagged **7 of 16 defects** (4 of 8, then 3 of 8) and **none** of the 4 intentional
  changes or the clean game ([blind runs](#all-blind-runs)).
- **The planner, measured blind once:** on set 2, with the clean game as each job's reference, Muse
  Spark's extra probes and contracts took it from 3 of 8 to **4 of 8**, still with no false alarm
  ([set 2](#set-2-blind-runs-3-and-4-november-1)). One more defect on one run of eight is a hint, not
  a measured gain. Its first attempt, on set 1, never answered (run 2).

## What runs

```
mechanics profile ──► templates ──► contracts (closed trace language)
  (claims read from                       │
   the game's code)                       ▼
probe library ──► route compiler ──► headless replays ──► episodes ──► evaluator ──► verdicts
  (generic moves)      (exact routes)      (one per probe     (normalized    (pure, no      │
                                            per build)         traces)        model)         ▼
                     Muse Spark planner (optional): more probes and contracts   reference check, then
                     from the profile and the build's measurements only         3-of-3 reproduction
                                                                                         │
                                                                                         ▼
                                                                          discovery-run/v1 + report
```

| Part | Where | What it does |
| --- | --- | --- |
| Records | [`contracts/*.v1.schema.json`](../contracts), [`expectrail/contracts.py`](../expectrail/contracts.py) | Five closed schemas: episode, trace-spec, trace-verdict, mechanics-profile, discovery-run. Strict JSON: duplicate keys, NaN and Infinity are refused. |
| Recorder | [`harness/godot/expectrail_harness.gd`](../harness/godot/expectrail_harness.gd) | Writes the enemies and bullets on every tick (an empty list means none) and declares what it collects, so an empty tick can prove absence. |
| Episodes | [`expectrail/trace/normalize.py`](../expectrail/trace/normalize.py) | One replay's trace as an episode: contiguous ticks, declared capabilities, derived events (take-off, landing, a bullet's first appearance, a disappearance the recorder can vouch for). Never fills a gap. |
| Interpreter | [`expectrail/trace/evaluator.py`](../expectrail/trace/evaluator.py), [`signals.py`](../expectrail/trace/signals.py) | The only thing that gives a contract meaning. Eight operators from the specification plus `relation`. Five outcomes with counts. |
| Probes | [`expectrail/discovery/probes.py`](../expectrail/discovery/probes.py), [`route_compiler.py`](../expectrail/discovery/route_compiler.py) | 22 generic probes from the action catalog, compiled to exact routes. Programs, never code: tap, hold, wait, sequence, parallel, repeat, with caps on ticks, events, nesting and repeats. |
| Profile and templates | [`discovery/platformer.profile.json`](../discovery/platformer.profile.json), [`templates.py`](../expectrail/discovery/templates.py) | Four claims read from the game's code, each `inferred_code` and unapproved, and twelve templates that turn them into contracts with no model involved. |
| Planner | [`expectrail/discovery/planner.py`](../expectrail/discovery/planner.py) | One Muse Spark call per job. It sees the profile, the probes already run and each build's measurements, under a number, never its name. Its probes must compile and its contracts must validate; anything else is dropped and recorded. Its contracts carry `model_prior` authority. |
| Job | [`expectrail/discovery/run.py`](../expectrail/discovery/run.py), [`cli.py`](../expectrail/discovery/cli.py) | Runs it all under a budget, writes the discovery-run record and a report. |
| CI | [`.github/workflows/discovery.yml`](../.github/workflows/discovery.yml) | One job per build, no reference build, planner off or Spark. |

### The five outcomes

- **pass**: the contract applied, triggered at least as often as it requires, its window was
  completely observed, and nothing contradicted it.
- **fail**: a concrete counterexample in observed data.
- **not_exercised**: nothing triggered it (no bullet, no jump, no movement). It is never a pass.
- **insufficient_observation**: the recorder did not collect what the contract needs, or the window
  has a gap.
- **execution_error**: the evaluation itself failed.

### Relations: a bound from the game itself

`relation` is our one addition to the specification's eight operators. It compares one measurement
between two probes that differ in one thing: eight jump presses against two, shooting every 12
ticks against every 48, walking left against walking right. The bound comes from the game's own
behaviour on the twin probe, so it needs no number from a person and no healthy build. That matters
for a bug that is already in the game.

### What makes a failure a finding

- **The reference check.** When the job has a healthy reference build, a contract that fails on it
  is miscalibrated: it is rejected, and whatever it says about another build is never a finding.
- **Reproduction.** Each failing contract's probes are replayed from a fresh process until they have
  run three times. Three failures make it `reproduced`; anything less is a `flaky_candidate`, with
  the counts.
- **Without a reference** (the CI jobs, one build each), nothing is falsified inside the job. The
  clean game's own job is the false-alarm control: a contract that fails on it would be a false
  alarm on every build.

## Results

### Local, October 31: the clean game and the four reported bugs

One job, the clean game as the reference and each reported bug as a base build, all 22 library
probes on each, planner off: 150 replays in 548 s on one machine (110 probes, 40 reproduction
replays), complete within budget.

| Build | Replays | pass | fail | not exercised | Findings, each 3 of 3 |
| --- | ---: | ---: | ---: | ---: | --- |
| clean (reference) | 22 | 91 | 0 | 64 | none, and no contract rejected |
| air-jump | 22 | 87 | 4 | 64 | eight presses give 7 kicks in the air, two give 1 (`jump-no-extra-air-jumps`, at all four positions) |
| gun-cooldown | 22 | 87 | 4 | 64 | bullets 12 ticks apart, minimum 30 (`weapon-min-interval`); tapping every 12 ticks fires 12 bullets, every 48 fires 3 (`weapon-faster-taps`, both directions) |
| body-flip | 22 | 84 | 7 | 64 | walking left while facing right (`facing-follows-motion`); a bullet flying right while the robot faces left (`facing-bullets-follow-facing`); the sprite turns 240 times walking left, never walking right (`facing-mirror`, twice) |
| enemy-ledge | 22 | 90 | 1 | 64 | an enemy drops 256 px below where it settled, while the robot stands still (`enemy-max-drop`) |

Each bug was found by at least one contract, and the clean game failed none. No contract names a
bug, replays a bug's route or takes a threshold from a bug report (see [What the development
results do and do not say](#what-the-development-results-do-and-do-not-say) for how the profile
was chosen). The guards held where the feature still works: the double jump still exists on every
build, a ready press still fires, the enemies are all still there and still patrol. "Not exercised" is
mostly a contract on a probe that cannot trigger it (a weapon rule on a jump probe). A second full
run gave the same 110 episodes tick for tick. The record: [`bench/discovery/local-oct31/`](../bench/discovery/local-oct31/report.md).

### CI

Run [41238187197](https://github.com/seanudeke/Expectrail/actions/runs/41238187197), October 31,
planner off: one job per build, each with no reference build, all 22 library probes, recorded from
the jobs' own notices in [`bench/discovery/run-41238187197.json`](../bench/discovery/run-41238187197.json).

| Build | Written for? | pass | fail | not exercised | Findings, each 3 of 3 |
| --- | --- | ---: | ---: | ---: | --- |
| clean | the false-alarm control | 91 | 0 | 64 | none |
| air-jump | yes | 87 | 4 | 64 | as in the local run |
| gun-cooldown | yes | 87 | 4 | 64 | as in the local run |
| body-flip | yes | 84 | 7 | 64 | as in the local run |
| enemy-ledge | yes | 90 | 1 | 64 | as in the local run |
| physics-fall-through v1 | no | 75 | 4 | 76 | the double jump no longer works (`jump-air-jump-exists`, all four positions) |
| physics-fall-through v2 | no | 59 | 20 | 76 | the same, and an enemy drops through the floor (`enemy-max-drop`) |
| sinking v1 | no | 91 | 0 | 64 | missed |
| sinking v2 | no | 91 | 0 | 64 | missed |
| missing-texture v1 | no | 91 | 0 | 64 | missed |
| missing-texture v2 | no | 91 | 0 | 64 | missed |
| layering v1 | no | 91 | 0 | 64 | missed |
| layering v2 | no | 91 | 0 | 64 | missed |

- **The four reported bugs and the clean game gave exactly the local counts** on a different machine.
- **The recorder change moved nothing else.** The reported-bug bench ran on the same commit
  ([run 41238187161](https://github.com/seanudeke/Expectrail/actions/runs/41238187161)): today's
  checks still catch none of the four, the engine-record checks still catch all four, and neither
  raises a false alarm on the clean game.
- **Two of the eight development bugs were flagged, by contracts written for something else.** In
  both fall-through variants the robot drops through the ground at once and never stands, so it
  cannot jump at all: the guard that the double jump still works fails. That is a true symptom, not
  the cause; the report says "no air jump", not "fell through the floor". In v2 the ground loses its
  collision for everything, and the enemy rule says so directly.
- **Six were missed, as expected.** Sinking v1 rests the robot inside the ground and no claim is
  about ground contact; sinking v2, missing texture and layering are visual and cannot show in a
  trace. The verifier's approved checks and SAM catch all six today.

## The blind run

The results above are development reproduction. The blind run is the test that is not:

1. **Freeze.** A freeze records the sha256 of every file that decides a finding (the profile and
   templates, probes, route compiler, signals, interpreter, job, planner prompt and model, record
   schemas, recorder, replay harness) and of the clean game, plus the exact blind command. Freeze 1
   (commit `0b6556c14a51`, kept as `discovery/freeze-1.json`) is what set 1 was written against;
   freeze 2 (`discovery/freeze.json`) is set 2's. `python -m expectrail.discovery.freeze verify`
   names any file that changed, and a test keeps the freeze holding on main while a set is in use.
2. **Fresh defects, written after the freeze.** Eight to ten defects and one or two intentional
   changes, in the private held-out repository (set 1 under `fresh/`, set 2 under `fresh-2/`), each
   with a private route showing it.
   They are written without the discoverer's rules in front of the writer, and chosen by a random
   draw from a longer written list, so nobody picks them for being easy or hard to catch.
3. **Commit the set's digest** here (`bugs/fresh/fresh.sha256`, `bugs/fresh/fresh-2.sha256`) before
   any run.
4. **Run once** with the Discovery blind run workflow
   ([`.github/workflows/discovery-blind.yml`](../.github/workflows/discovery-blind.yml)). It verifies
   the freeze and the digest before replaying anything, runs the clean game as a control, and uses
   no reference build. The public log carries counts only: per opaque id,
   defect or intentional, flagged or not. Which rules fired stays private until the event is over.

Scored: defects flagged out of defects, intentional changes and the clean game flagged (false
alarms), and incomplete jobs. A miss is a result, not a reason to change the frozen system.

### Blind run 1, October 31

Run [41248745687](https://github.com/seanudeke/Expectrail/actions/runs/41248745687), main at
`81f692c`, planner off. Before replaying anything, every job verified the freeze (`6e9ca2bd…`) and
the set's digest against [`bugs/fresh/fresh.sha256`](../bugs/fresh/fresh.sha256). Recorded from the
jobs' counts-only notices in
[`bench/discovery/blind-run-41248745687.json`](../bench/discovery/blind-run-41248745687.json).

| Id | Kind | Flagged | Reproduced findings | Replays |
| --- | --- | --- | ---: | ---: |
| clean | control | no | 0 | 22 |
| f01 | defect | **yes** | 1 | 24 |
| f02 | defect | **yes** | 4 | 38 |
| f03 | intentional | no | 0 | 22 |
| f04 | defect | no | 0 | 22 |
| f05 | defect | no | 0 | 22 |
| f06 | defect | **yes** | 1 | 24 |
| f07 | defect | no | 0 | 22 |
| f08 | defect | no | 0 | 22 |
| f09 | defect | **yes** | 4 | 38 |
| f10 | intentional | no | 0 | 22 |

**4 of 8 defects flagged, 0 false alarms on 3 healthy builds, 0 incomplete jobs.** Every flag
reproduced three times out of three; no finding was flaky.

What it does and does not show:

- **It is the first discovery result on defects nobody tuned the discoverer to.** They were written
  after the freeze, by a separate session that never saw the discoverer's rules, and chosen by a
  seeded random draw from a list of sixteen candidate defects committed first.
- **Eight defects is a small sample.** 4 of 8 says the slice reaches some unseen defects; it does
  not estimate a rate.
- **The writer was not fully independent of us.** The prompt it followed was written by the session
  that built the discoverer, and it suggested the areas to draw from (walking, jumping, shooting,
  enemies, coins, collision, the camera and more), which include the four mechanics the profile
  covers. The writer was an AI agent, not a person.
- **The set's descriptions reached the discoverer's author before the run.** The freeze, verified by
  the run before it replayed anything, is what guarantees the discoverer did not change after that.
- **Which rules fired, and what each entry is, stay private until the event is over,** like the
  held-out bugs. The ids, kinds and flags above are what the run published.

### Blind run 2, planner on: the planner never answered

Run [41250932288](https://github.com/seanudeke/Expectrail/actions/runs/41250932288), the same frozen
set, dispatched with the Muse Spark planner on. Every job verified the freeze and the digest, then
recorded the planner stage as **unavailable**: every Spark call came back with no content. The jobs
ran the templates alone and gave run 1's result exactly: **4 of 8 defects, 0 of 3 healthy builds,
no incomplete job** ([`bench/discovery/blind-run-41250932288.json`](../bench/discovery/blind-run-41250932288.json)).
So the frozen discoverer gave the same answer twice, and **the planner-on condition has not been
measured.**

Why, found afterwards on public builds only: Muse Spark reasons before it answers, and its reasoning
counts against the 4,096-token limit the planner sent, so nothing was left for the answer (the same
public run with the limit removed used 10,000 to 22,000 completion tokens a call). That fix is in
`expectrail/discovery/planner.py`, a frozen file. Rather than change the discoverer under a set
whose descriptions its author had already seen, set 1 is retired and a new set is written against a
new freeze (next).

### Freeze 2 and fresh set 2

- **Freeze 2** (`discovery/freeze.json`, `9af1f621…`) differs from freeze 1 (kept as
  `discovery/freeze-1.json`, `6e9ca2bd…`) in one frozen file, `expectrail/discovery/planner.py`: the
  planner sends no token limit and names an empty answer as such. The blind command also changed:
  with the planner on, each job replays the clean game as its reference, so a model's contract that
  fails on it is rejected (the reason is in the next section). The probes, profile, templates,
  signals, interpreter, job, schemas, recorder, harness and clean game are byte for byte the same.
  `tests/test_discovery_freeze.py` checks both.
- **Fresh set 2** is written the same way as set 1, after freeze 2, in the private repository under
  `fresh-2/` (ids `g01` to `g10`), by a new session that has not seen set 1, this repository's
  discovery code or its docs. Its digest goes in `bugs/fresh/fresh-2.sha256` before any run. Set 1
  stays where it is; the blind workflow refuses it under freeze 2, because its manifest names
  freeze 1.
- **Two runs on set 2:** planner off, then planner on, each once. Set 2's planner-off result is a
  second blind sample of the frozen templates; the planner-on result is the planner's first blind
  measurement.
- **Freeze 2 retired, November 9, 2026.** Both runs on set 2 are recorded (below), so discovery's
  files may change again. `discovery/freeze.json` is kept as the record of what set 2 ran against,
  and `tests/test_discovery_freeze.py` now checks it against commit c169a5e, the hackathon
  submission, instead of main. `python -m expectrail.discovery.freeze verify` fails on main once a
  frozen file changes; run it on that commit to check the record. The blind workflow verifies the freeze first, so it refuses
  as soon as a frozen file changes, and set 2 has been seen, so a new blind claim needs a new freeze
  and a new fresh set.

### The planner, live on public builds

Measured on the public builds (the clean game, the four reported bugs, the eight development
variants), not blind, on branch `discovery/planner-fix` before it merged:

| Run | Planner | Reference | What happened |
| --- | --- | --- | --- |
| [41251362155](https://github.com/seanudeke/Expectrail/actions/runs/41251362155) | 4,096-token limit | none | No content from any call; the planner stage unavailable in every job |
| [41251642563](https://github.com/seanudeke/Expectrail/actions/runs/41251642563) | no limit | none | It answered everywhere: 4 probes and 2 to 7 contracts a build (10,000 to 22,000 completion tokens a call). With nothing to falsify them, its contracts were reproduced 3 of 3 on the **clean game** (2) and on 4 of the 5 visual-only builds that reported. 12 of 13 jobs reported |
| [41252054622](https://github.com/seanudeke/Expectrail/actions/runs/41252054622) | no limit | the clean game, in each job | 61 contracts proposed, 13 rejected because they failed on the clean game. No model finding on the clean game or any visual-only build; model findings only on gun-cooldown, both fall-through variants and body-flip, all already flagged by the templates. 12 of 13 jobs reported (enemy-ledge's job never got past installing packages on its runner) |

So on public builds the planner adds second reasons, not new detections, and without a healthy
reference its contracts are false alarms waiting to happen. Records: `bench/discovery/run-41251642563.json`,
`bench/discovery/run-41252054622.json`.

### Set 2: blind runs 3 and 4, November 1

Fresh set 2 was written after freeze 2 was merged (pull request #159, 14:13 UTC): its candidate list
was committed to the private repository at 14:19, the set at 14:42, and its digest here in pull
request #166 at 14:42. Both runs were dispatched on #166's head (`a5ae587`), and every job verified
freeze 2 (`9af1f621…`) and the digest (`3306391f…`) before replaying anything. Recorded from the
jobs' counts-only notices in [`bench/discovery/blind-run-41319184209.json`](../bench/discovery/blind-run-41319184209.json)
(planner off) and [`bench/discovery/blind-run-41319197682.json`](../bench/discovery/blind-run-41319197682.json)
(planner on).

| Id | Kind | Run 3, planner off | Run 4, planner on |
| --- | --- | --- | --- |
| clean | control | no | no |
| g01 | intentional | no | no |
| g02 | defect | no | no |
| g03 | defect | **yes** | **yes** |
| g04 | defect | **yes** | **yes** |
| g05 | defect | no | no |
| g06 | defect | no | **yes** |
| g07 | defect | no | no |
| g08 | defect | **yes** | **yes** |
| g09 | intentional | no | no |
| g10 | defect | no | no |

- **Planner off: 3 of 8 defects, 0 of 3 healthy builds,** every finding 3 of 3, no job incomplete.
- **Planner on: 4 of 8, 0 of 3.** Muse Spark answered in every job. Each job replayed the clean
  game as its reference, so any of its contracts that failed there was rejected before it could
  count; none of its contracts raised a finding on either intentional change or the clean game.
  The extra defect is g06. The planner-on jobs replayed 52 to 76 episodes each, against 22 to 38
  with it off, and took about two to three times as long.
- **What it does not show.** One planner run on one set of eight: a single extra catch could be
  luck, and Spark's proposals vary from run to run. Which rules fired and what each entry is stay
  private until the event is over. The writer was again an AI session following a prompt written by
  the discoverer's author; it never saw set 1, the discovery code or its docs.

### All blind runs

| Run | Set | Freeze | Planner | Defects flagged | Healthy builds flagged | Incomplete |
| --- | --- | --- | --- | --- | --- | --- |
| 1, [41248745687](https://github.com/seanudeke/Expectrail/actions/runs/41248745687) | 1 | 1 | off | 4 of 8 | 0 of 3 | 0 |
| 2, [41250932288](https://github.com/seanudeke/Expectrail/actions/runs/41250932288) | 1 | 1 | on, but it never answered | 4 of 8 | 0 of 3 | 0 |
| 3, [41319184209](https://github.com/seanudeke/Expectrail/actions/runs/41319184209) | 2 | 2 | off | 3 of 8 | 0 of 3 | 0 |
| 4, [41319197682](https://github.com/seanudeke/Expectrail/actions/runs/41319197682) | 2 | 2 | on, the clean game as reference | 4 of 8 | 0 of 3 | 0 |

The frozen templates alone, on the two independent sets: **7 of 16 defects, no false alarm on the 4
intentional changes or the clean game.** That is still a small sample, from two sets written by AI
sessions, not a rate for defects in general. Two entries, one in each set, turned out to share a
mechanism (their writers never saw each other's sets), and one flagged entry overlaps part of a
reported bug's mechanism, which the profile was written after. Counting each mechanism once and
leaving that entry out, the templates flagged **5 of 14**. The entries themselves are published
after the event.

### Shortcut fixes and healthy retunes, November 1

A guard is a contract that the feature still works. The test of a guard is a "fix" that makes a
symptom go away by disabling the feature, which it should flag, and a deliberate retune, which
nothing should flag. Six such builds ([`bugs/challenges/`](../bugs/challenges/README.md)) ran beside
the thirteen public builds in run [41326269491](https://github.com/seanudeke/Expectrail/actions/runs/41326269491),
planner off ([`bench/discovery/run-41326269491.json`](../bench/discovery/run-41326269491.json)):

| Build | What it does | Result |
| --- | --- | --- |
| shortcut-no-double-jump | removes the air jump (a "fix" for unlimited air jumps) | flagged: the double-jump guard, at all four positions |
| shortcut-gun-never-fires | the gun never fires (a "fix" for the cooldown bug) | flagged: the ready-press guard |
| shortcut-no-turning | the sprite never turns (a "fix" for the body flip) | flagged: the robot walks left facing right |
| shortcut-enemies-stand-still | enemies stand still (a "fix" for walking off ledges) | flagged: the patrol guard |
| healthy-faster-walk | the robot walks 10% faster | no finding |
| healthy-faster-enemies | enemies patrol a little faster | no finding |

**4 of 4 feature-disabling fixes flagged, 0 of 2 retunes.** We wrote these knowing the guards, so
they show the guards do their job, not a blind result. The thirteen public builds in the same run
gave exactly the counts of run 41238187197.

## What the development results do and do not say

- **This is development reproduction, not discovery.** The profile's four claims (the double jump,
  the gun's cooldown, the sprite's facing, the enemies' patrol) and the probe families were written
  by the same team, on the same day, after reading the four bug reports, and the contract that catches
air-jump was added after the first jump contract missed it (next point). No bug report, patch, route
  or hand-written rule went into a run, and every threshold comes from the game's own code or from
  a twin probe, but the choice of what to profile was not blind. The record says so: its condition
  is `development-reproduction`, and it lists what was withheld.
- **The eight development bugs are the check on that.** Nobody wrote a claim for them. Ground contact
  (fall-through, sinking) is not in the profile, and the two visual families (missing texture,
  layering) cannot show in a trace at all; the verifier's approved checks and SAM already cover them.
  Expect misses there: they show the slice reaching only what the profile claims.
- **One contract we expected to catch air-jump did not, and its replacement was written after that
  miss.** The profile bounds the rise above the floor at two full jumps (260 px). The game cuts a
  jump short when the button is released, so short taps never come near it, with the bug or without.
  After seeing that on the air-jump build, we added a signal for the number of upward kicks in one
  stretch of air and switched the twin-probe relation to it (eight presses against two). That is
  tuning against the case, so the air-jump catch is the weakest of the four. The specification warns
  against counting impulses from position alone; on the clean game the count was 0 for one press and
  1 for two or more on all twelve jump probes at four positions, and never above 1 on any of the 22
  probes, and the relation compares two probes from the same spot rather than asserting a number. A
  moving platform, a slope or a stomp could still add a kick.
- **No frames.** Discovery replays headless and reads the trace only, about four times faster. The
  physics is identical (the traces match tick for tick; only the camera's view transform differs, and
  no contract reads it). A finding names its probes, so its replay can be rendered with frames.
- **Nothing is approved.** Every claim is `inferred_code` with no approval, so every contract is
  advisory. Promotion into the verifier (approval, validation against causal variants and
  feature-removal challenges, paired verdicts, signing) is the specification's next stage and is not
  built.
- **The four reported bugs are not the blind claim.** A blind-discovery claim needs fresh defects
  under a frozen protocol; the four public reproductions cannot provide it. Blind run 1 above is
  that test: 4 of 8, on a small set.

## What's next

In order, and none of it built yet unless it says so.

1. **More blind evidence, from people.** Two sets of eight defects, both written by AI sessions,
   give 7 of 16 for the templates and one planner run. A larger set written by people outside the
   team, and the planner run several times on it, are what a rate or a planner claim would need.
2. **A finding should name its cause.** Development catches came through rules written for
   something else (a fall-through flagged as "no air jump"). A reviewer can replay the
   probe, but the report should say what changed, not only which rule tripped.
3. **The rest of the autonomous-discovery specification.** The team's specification has three
   rollouts:
   - *Advisory* (this page is its first slice). Still to come: visual discovery (Muse Spark proposes
     the scene's entity classes, SAM 3.1 finds each, base and candidate compared on matched runs),
     planner rounds between episodes rather than one call, and integrity signals (crashes, fatal
     script errors, non-finite state, no progress) recorded apart from suspected gameplay defects.
   - *Promotion.* Each contract moves through proposed, reproduced, validated, shadow and approved or
     rejected, as append-only registry events. Validation needs at least ten clean runs across three
     healthy configurations, at least two faulty variants from distinct causes and one
     behaviour-preserving patch, guards that reject a fix which disables the feature, and
     applicability tests. A person approves the profile and its templates; a model's proposal never
     approves itself. Validated contracts then run in shadow beside the verifier.
   - *Enforcement.* A project opts in to verification v1 with a pinned contract set: paired verdicts
     against the failing base (repaired, preserved, regression, unresolved, inconclusive), repair
     requests for faults found in the trace rather than on screen, and signing of the exact scope.
     Only then can a discovered contract reject a change.
4. **What we would take from AI code review that runs code.** Greptile's TREX runs the code a pull
   request changes in a sandbox and attaches logs, screenshots and video to its review. Our Greptile
   strategy-adoption specification maps seven of its ideas onto Expectrail; their status:

   | Package | Status | What is left |
   | --- | --- | --- |
   | G01 Map a change to the behaviours it can affect | Not built | A small index of scenes, scripts and resources, linked to profile claims and probes, used to pick probes for a diff; compared with a planner that sees only the diff |
   | G02 One question per investigation | Partly: one planner call proposes probes and contracts | Typed hypotheses with stop conditions, and a ledger that reuses episodes |
   | G03 Confirm findings automatically | Mostly built: identities, not-exercised outcomes, 3-of-3 reproduction, reference falsification, the clean control, guards | Causal variants, feature-removal challenges and healthy variations per contract (the promotion validation above) |
   | G04 Evidence in the pull request | Partly: review pages with paired before-and-after verdicts ([review.md](review.md)), the morning report, CI summaries | A pull request comment with finding ids that stay stable across pushes, posted from a separate trusted step |
   | G05 Allocate models, replays and budget | Largely built: report-first escalation, the judge fallback ladder ([fallbacks.md](fallbacks.md)), job budgets, headless trace-only replays | One budget across planning, replays and judging |
   | G06 Scoped memory of team feedback | Not built | Typed feedback, with approved expectations kept apart from preferences |
   | G07 Import Greptile's findings | Not built | Read-only import of its review comments as hypotheses (GitHub comments, its MCP read tools, or its CLI's JSON output); kept only if it adds confirmed findings |

   G01 and G02 change the frozen planner, so they wait for the blind run. Every value claim in that
   specification (context improves detection, routing saves money, and so on) needs a measured
   comparison before we make it.

## Run it

```
export PATH="$PWD/tools/godot:$PATH"
python -m expectrail.discovery.cli discover --profile discovery/platformer.profile.json \
    --snapshot clean:reference --snapshot air-jump:base:bugs/reported/air-jump.patch \
    --out runs/discovery [--planner spark] [--probes jump-w0-x2,jump-w0-x8]
python -m expectrail.discovery.cli report runs/discovery/discovery-run.json
```

In CI: dispatch the Discovery workflow (planner `off` or `spark`; Spark needs `MODEL_API_KEY`), then
record it with `python -m expectrail.discovery.cli collect --run <id>`, which reads the jobs'
notices into `bench/discovery/`.
