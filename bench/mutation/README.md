# Mutation bench

How much does Expectrail's tiered checker catch, which checks catch what, what does it miss, and what
did the judging cost? Issue #127 sets the rules. Nobody on the team writes a bug or picks a case.

**Status: registered, and all three parts are recorded.** See [Results](#results). `agents/mutation_bench.py` and the
**Mutation bench** workflow refuse to run until [`preregistration.json`](preregistration.json) has no
empty field left, the code it pins has not moved, and the committed manifest is exactly what the
generator writes. A judged run starts only from `main`, so nothing is judged before the file is merged.
Rehearsals prove the plumbing first, on any branch, on cases the study cannot draw: `dry-run` (the
judge benchmark's public comment-only fixture on an unfixed bug, no SAM, no key), `dry-run-sam` (the
same pair through forced SAM, about $1.20) and `dry-run-mutants` (three stand-ins in files the generator never edits, no SAM,
no key). A rehearsal is never a result: it has no score, its rows name no registration, a summary
refuses to mix it with a judged run, and it fails if it did not reach what it rehearses. The
pre-registration discloses what earlier rehearsals, on members of the population, happened to show.

Three cases judged before registration are excluded before the draw, by Sean's decision, whatever
they did: the `freeze` pair on physics fall-through v1 and two mutants (`excludedBeforeDraw`). So Part 1
is 47 pairs, not 48. The registration names them, and the manifest lists them.

The pins cover the game, the development bugs, the operators, the specs, the verifier, the observers,
the generator, the bench and its workflow. Changing any of them after registration refuses every run
until the pins are set again, which is a change to the registration and has to be reported as one.

### Reproducing the bench

Since November 9, 2026, the registration describes commit `c169a5e`, the hackathon submission, and
main may change the files it pins. Judged runs of the **Mutation bench**, **Mutation fix** and
**Mutation record** workflows still start from main, but check out that commit, so the code they run
is the code the pins describe. On main itself, `agents/mutate_game.py` refuses a judged run and names
the commit. `tests/test_mutation_registration.py` checks that the registration file is unchanged and
that it still loads against an extract of the commit. Rehearsals are unchanged: they run the branch they start from.

## Results

Registered in #164, commit [`a439e9b`](https://github.com/seanudeke/Expectrail/commit/a439e9b558f4cd5ebc742d97a5f4c349121d622b),
before any case in the study was judged. Each record is written by `agents.mutation_collect` from its
runs' own artifacts and is not edited by hand. Public checks only.

| Part | Cases | Result | Spend | Runs | Record |
| --- | --- | --- | --- | --- | --- |
| 1, wrong fixes | 47 pairs: 39 labelled bad, 8 good | Score **79.5%**: 31 of 39 caught, 7 by the cheap tier, 24 only with SAM. All 8 good cases accepted | 5,473 SAM images, $13.68 | [41268021760](https://github.com/seanudeke/Expectrail/actions/runs/41268021760) | [`wrong-fix/`](wrong-fix/README.md), [notes](wrong-fix/NOTES.md) |
| 2, generated bugs | 150 sampled: 73 equivalent, 77 judged | Weighted score **0.9%**, weighted over every class with a visible mutant (boolean's one mutant was equivalent). Over the sample as drawn, a figure about the sample: 13.0%, 10 of 77 caught, 5 by the cheap tier, 5 only with SAM | 15,862 SAM images, $39.66 | [41268023631](https://github.com/seanudeke/Expectrail/actions/runs/41268023631), [41323827584](https://github.com/seanudeke/Expectrail/actions/runs/41323827584), [41323829361](https://github.com/seanudeke/Expectrail/actions/runs/41323829361) | [`generated/`](generated/README.md) |
| 3, AI-written fixes | The 10 generated bugs Part 2 caught, 1 candidate each | Muse Code fixed all 10 on the first attempt and Expectrail accepted all 10. The oracle labelled all 10 good, on 6 routes, 5 of which the judge does not use. **0 natural catches**, 0 false accepts, 0 false rejects. Muse from screenshots rejected 5 of the same 10 | 250 SAM images, $0.62 | [41330361829](https://github.com/seanudeke/Expectrail/actions/runs/41330361829) | [`ai-fixes/`](ai-fixes/README.md) |

SAM spend across the three parts: $53.96. Muse Code's own cost is not reported per run, so it is not
in that figure.

#175, Part 2's record, was merged before review. Taofeek, working with a separate AI agent session, then
reproduced it byte for byte from the runs' artifacts: `README.md`, `summary.json` and `findings/` all
match. #179, Part 3's record, was reproduced the same way before it merged, and its patches and
prompts were read from the run's artifacts. That shows the records are what the runs produced. It uses the
same recorders, and it does not rerun the judging.

Part 2 by class:

| Class | Mutants in the game | Sampled | Equivalent | Judged | Caught | Score |
| --- | --- | --- | --- | --- | --- | --- |
| numeric | 2,642 | 70 | 25 | 45 | 0 | 0.0% |
| resource-path | 65 | 30 | 15 | 15 | 3 | 20.0% |
| code | 19 | 19 | 5 | 14 | 5 | 35.7% |
| collision-bit | 65 | 30 | 27 | 3 | 2 | 66.7% |
| boolean | 1 | 1 | 1 | 0 | 0 | none |

What these numbers say:

- **On wrong fixes, the checks catch what the operators really break.** Every `freeze`, `hide`, `sink`
  and `behind-scenery` candidate was caught. The other 8 bad-labelled cases are `scale-to-zero`, which
  changes nothing in the running game: the Player instance in `game_singleplayer.tscn` overrides the
  scale. They stay in the score as registered, and [the notes](wrong-fix/NOTES.md) explain them.
- **On generated bugs, most of what differs from the clean game goes unseen.** 67 of 77 judged mutants
  survived. The numeric class sets the weighted score, because it holds nearly all the estimated
  visible mutants, and it caught 0 of 45. 44 of those move, resize or re-layer scenery that no check
  covers. Under an oracle of 0 pixels and 0 frames, any change to what is drawn counts as a bad case.
  Many of these may not be bugs a player would report, but the bench cannot say which.
- **The 45th numeric survivor is a real miss.** `numeric:player/player.tscn:204:position.x-` moves the
  player's `Sprite2D` 26 px left of its body, so the robot is drawn away from where it collides. A
  player could notice that, and nothing catches it: `player-always-visible` still passes.
- **The other survivors are the more useful list.** 9 code, 12 resource-path and 1 collision-bit
  mutants survived. Each has a finding that records what every check said, but no catch-spec: the
  bench writes those per wrong-fix operator, so only Part 1 has them. Which check would catch each
  generated survivor is still to be worked out. No check was added after seeing a result.
- **Cheap checks and SAM catch different things.** Part 1 has 24 vision-only wins and Part 2 has 5.
  Agreement is 0 of 12: SAM's own checks passed all 12 cheap rejections they were asked about (7 in
  Part 1, 5 in Part 2). SAM did not contradict those catches, since it looks for different failures, but it cannot
  stand in for the cheap tier, and this sample does not show the two tiers giving the same answer.
- **The tier saved little on generated bugs.** Part 2 spent 14,273 images on the tiered judge against
  15,305 for a full run, because 72 of 77 cases reached SAM.
- **Part 3 had nothing to catch.** Muse Code wrote no fix that only looked right, so Part 3 says nothing
  about Expectrail's catch rate. Every candidate gave exactly the clean game on all 6 label routes: 0 px
  of trace difference and 0 frames different. 7 are exact undos of the bug. 2 restore the jump velocity
  as `-725` rather than `-725.0`, and 1 swaps two branches, which plays the same. What Part 3 does show,
  on 10 cases: Expectrail rejected no correct AI-written fix, and Muse judging from screenshots rejected 5.

## Limits of these results

- Part 1's operators were written by the team, and one of them, `scale-to-zero`, turned out to do nothing.
- The generator's operator list defines what "a bug" means here. It reaches scenery far more often
  than game logic, and stratifying the sample does not change that for the weighted score.
- The oracle only knows "differs from the clean game", so this measures regressions, not new features.
- Public checks only. The held-out arm is excluded from every decision here.
- Taofeek dispatched Part 1 and Part 2's cheap tier. An AI agent, the one that built most of
  Expectrail, dispatched and recorded Part 2's SAM phase and Part 3, from lists the registration
  fixes (`--plan-sam`, `cases.json`). The safeguards are the registration and Taofeek's reproduction
  of the records.
- Three cases were judged in rehearsals and excluded before the draw: one wrong-fix pair, so Part 1 is
  47 pairs, not 48, and two mutants, which Part 2's draw could not pick.
- #170 changed `agents/judge_bench.py`, a pinned file, at 16:10 UTC on Nov 1, and the registration
  refused to load until #174 restored it byte for byte at 16:54. No judged run started in that window:
  the SAM runs started at 15:57 on `5cf2e0a` and Part 3 at 17:13 on `764e7fc`, and the one record
  attempt in between was refused.
- The registration's values, including the sample, the steps and the 0/0 oracle, were drafted by an AI
  agent, adopted by Taofeek, and not reviewed by anyone else before the first run. #127 had reserved
  those choices for a person. `decisionProvenance` in the registration records where each came from.
- The agreement sample is 5 in Part 2, below the registered minimum of 20, because only 5 cheap
  catches exist. All 5 were used.
- Part 3's label rule changed before anything ran, from engine record only to the registered oracle,
  positions and frames (#168).
- Part 3's seed decided nothing: Part 2 caught exactly 10 mutants and Part 3 samples 10, so the case
  list is every catch. They are bugs the checks already catch, and each report is built from the
  catching check's sentence.
- In Part 3 the fixer got the registered report, the route, six screenshots and the game log, with no
  spec and no verdict. Ten cases is a small sample.
- Part 3's label routes are the five reported-bug routes, which the judge does not use, and the smoke
  route, which it does. The record's own sentence says "on routes the judge does not use"; that is
  wrong for the smoke route, and the record is left as written.
- The specs judge the first two seconds of one route, so anything a mutant breaks later or elsewhere
  reads as a survivor or as equivalent.

## What a person decides before anything is judged

| Field | Who | What |
| --- | --- | --- |
| `wrongFix.commentOnlyLabel` | Sean | `good` or `bad`. A comment stacked on the correct undo leaves the game correct, so #127's "bad by construction" does not hold for these 8 of the 48 pairs. |
| `wrongFix.publicSamRuleApprovedBy` | Sean | Approves leaving the verifier's held-out arm out of the bench's decision. Without this rule, SAM-on can never accept here. |
| `generator.*` | Taofeek | Seed, sample size and the operator steps. |
| `generator.sampling`, `generator.samplingWhy` | Taofeek | `{"method": "uniform"}`, or `{"method": "stratified", "perClass": {"numeric": n, ...}}`, whose counts must add up to `sampleSize`; and why. A class with fewer mutants than its count gives all it has, the manifest reports the shortfall, and the rest is never moved to another class. |
| `oracle.traceThresholdPx`, `oracle.frameThreshold` | Taofeek | What counts as visible. |
| `stopRule` | Taofeek | What happens if few mutants are visible. |
| `agreement.seed`, `agreement.minimum` | Taofeek | The seeded sample of cheap rejections SAM also judges. Sean asked for at least 20. |
| `reportTemplate` | Taofeek | The one-line symptom for Part 3. |
| `pins` | Taofeek, last | `python3 -m agents.mutate_game --pins`, once everything else is final. |

To register, put your decisions in a file by their dotted names (the list is at the top of
`agents/mutation_register.py`) and run:

    python3 -m agents.mutation_register --values decisions.json          # checks, and writes nothing
    python3 -m agents.mutation_register --values decisions.json --write

It writes your decisions and Sean's two, then the pins last, then the manifest, and reads both back
through the gates a judged run uses. It never overwrites a registration, and never pins uncommitted
work. Commit both files in one pull request, and say it is the registration.

## Recording a run

    python3 -m agents.mutation_collect --part wrong-fix --run <id>                 # Part 1
    python3 -m agents.mutation_collect --part generated --run <cheap>              # Part 2, the cheap tier
    python3 -m agents.mutation_collect --plan-sam --run <cheap>                    # what the SAM phase needs
    python3 -m agents.mutation_collect --part generated --run <cheap> --run <sam>  # Part 2, both phases

It reads the runs' own artifacts, counts a mutant judged in both phases once, reports any case missing,
and refuses a rehearsal, another registration or the wrong part. The tools are not pinned.

Without a machine that can download run artifacts, the **Mutation record** workflow runs the same
commands inside Actions, from `main`. `plan-sam` prints the plan as notices and in the run's summary.
`record-generated` and `record-ai-fixes` push what the recorder wrote to a new `bench/record-*` branch.
Open a pull request from that branch for review; the workflow never writes to `main`.

## Part 3

`agents/mutation_fix.py` and the **Mutation fix** workflow. `reportTemplate` must hold `{sentence}`, which
takes the sentence of the check that caught the mutant, so no report is written by hand.

    python3 -m agents.mutation_fix --pick --seed <your seed>   # after Part 2 is recorded; commit cases.json
    python3 -m agents.mutation_fix --estimate                  # post this in #156 first
    python3 -m agents.mutation_fix --record --run <id>

Each candidate is labelled by the registered oracle, positions and frames both, on routes the judge does
not use: bad if any route's engine record or frames differ from the clean game's by more than the
registered thresholds, or the game will not run there twice. A fix that puts every position back but
still draws the game wrong is bad, so a catch only vision can make is not scored as a false reject. A
route whose clean game does not match itself, in positions or frames, is not used, and a candidate
that only such routes could decide is unknown.

The workflow's `rehearsal` mode runs the path on a stand-in, with no Muse, no SAM and no key.

## What the operators can reach

From `python3 -m agents.mutate_game --sites`, one mutant per axis and direction with one collision
bit. These are facts about the game, and they bear on the operator list and the sample:

| Operator | Mutants |
| --- | --- |
| `position` | 1,268 |
| `scale` | 828 |
| `z_index` | 506 |
| resource path | 66 |
| `offset` | 40 |
| comparison, sign and constant in `player.gd` and `enemy.gd` | 20 |
| `collision_mask`, `collision_layer`, one bit | 13 |
| `one_way_collision` | 1 |
| `visible`, `disabled` | **0** |

`python3 -m agents.mutate_game --mutants-by-class` gives the same counts at the steps in the
pre-registration, once they are filled in.

Godot leaves a property out of a scene file when it holds its default, so `visible` and `disabled`
have no line to flip. An unstratified sample of this list is nearly all `position`, `scale` and
`z_index` in the level's scenery.

## How to read a stratified score

With counts set per class, the pooled score over the sample depends on those counts: a class of 13
mutants given as many cases as a class of 2,642 counts as much. So the report leads with a weighted
score, shows the pooled figure as a figure about the sample, and gives every class's own score.

A class's score is over its decided cases, so it weighs what it is estimated to hold of those: its
size times the share of its sample that was decided. Its plain size would count scenery edits nobody
could ever catch. A class with no score is named and left out of the weights, and the report says what
share of the estimated visible mutants the score covers. The estimate is only as good as each class's
sample: a class sampled lightly has a rough share and a rough score.

## How a case is scored

Only a check that ran to completion and failed is a catch. See `agents/mutation_bench.py` for the
outcomes (`caught-cheap`, `caught-sam`, `survived`, `undecided`, `crash`, `error`). The mutation score
is caught over caught plus survived, on cases labelled bad; everything else is reported beside it.

**Limits to state with any result.** The tier is this bench's policy: the verifier itself runs SAM on
every candidate. The specs judge the first two seconds of one route, and the smoke route never
shoots, so a mutant in the gun reads as equivalent. The oracle only knows "differs from the clean
game". Public checks only.
