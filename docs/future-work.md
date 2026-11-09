# Future work: known limits and what comes next

Expectrail independently checks changes made by AI coding agents: the agent that writes a change
cannot certify it. This ten-day hackathon build runs scripted routes through one Godot demo game,
using bugs we seeded and four reproductions of publicly reported Godot bugs. The limits below
describe what it cannot do today, what we would build next, and which parts could carry over
beyond games.

## What it is today

- One game: Godot's 2D platformer demo, one level.
- One way to play: scripted routes, replayed on exact physics ticks.
- Four bug families (physics fall-through, missing texture, layering, sinking), with two public
  development variants and two private held-out variants each, plus the clean game
  ([evaluation plan](evaluation.md), results in [`bench/`](../bench)).
- Four reproductions of publicly reported Godot bugs (`bugs/reported/`), caught by five
  engine-record checks that were written after the bugs were reproduced and that only the
  reported-bug bench runs so far ([`bench/reported/`](../bench/reported/README.md)).
- Two kinds of checks. Checks people wrote (three approved specs, the gameplay check, the held-out
  cases) are the gate. Checks Expectrail discovers (22 generic probes judged by rules read from the
  game's code) only advise: they found the four reported bugs with no false alarm, as a development
  result, and blind, on ten fresh entries written after they were frozen, they flagged 4 of 8 defects
  and no healthy build ([discovery.md](discovery.md)).
- One kind of agent change: repairs of a reported bug.
- Four visual assertion types: visible, inside-region, never-crosses and reaches.
- A fixer that writes small patches in its own worktree, inside bubblewrap in the live runs (only
  the worktree mounted; network on, because it calls Meta's API) and deny-by-absence without it (a
  worktree that does not contain the verifier's files), a separate verifier, and a person who
  approves the release candidate.

## Finding bugs

**It replays; it does not explore.** A route is a fixed list of inputs, and the 22 discovery probes
are a fixed library. A bug that only shows up where no route or probe goes stays invisible, so
today Expectrail is closer to visual regression testing than to playtesting.

Next:
- Record routes from human playtest sessions. The harness already replays inputs on exact ticks;
  recording them is the missing half.
- Take routes from exploring agents and from bug reports filed by testers or playtesting tools, and
  keep each one as a regression route.
- Report coverage: which levels, states and objects a night actually exercised.
- Let the discovery planner choose probes between episodes, in rounds, instead of one call per job
  (part of the autonomous-discovery specification below).

**Checks come from people, and only those can reject a change.** Every check in the verifier starts
as one sentence a person writes and approves. Advisory discovery ([discovery.md](discovery.md)) adds
checks nobody wrote: generic probes judged by contracts read from the game's code, reported when
they fail 3 times out of 3. It does not gate, its profile is not approved, and it reaches only the
four mechanics the profile claims; it found the four reported bugs, which its profile was written
after, 2 of the 8 development bugs, which it was not, and blind, 4 of 8 fresh defects written after
it was frozen.

Next, for the checks people write:
- Have Muse Spark draft specs from design documents and past bug tickets, still approved by a person.
- Grow a spec library for common bug families: the three we have, then text overflow, softlocks and
  motion jitter, which the evaluation plan already defers.

Next, for discovery (detail in [discovery.md](discovery.md#whats-next)):
- Measure the Muse Spark planner on more than one blind run. On fresh set 2 it took the templates
  from 3 of 8 to 4 of 8 with no false alarm, once; on public builds it added second reasons but no
  new detection.
- Make a finding name its cause, not only the rule that tripped: several catches came through a rule
  written for something else.
- A larger blind set, written by people outside the team, before any rate is claimed.
- The rest of the team's autonomous-discovery specification: visual discovery on matched base and
  candidate runs; integrity signals (crashes, script errors, no progress) kept apart from gameplay
  findings; then promotion (a person approves the profile, each contract is validated on clean runs
  across healthy configurations, faulty variants from distinct causes and feature-removal
  challenges, then runs in shadow); then enforcement (paired verdicts against the failing base, a
  pinned contract set, repair requests for faults found in the trace, signing). Only after
  enforcement can a discovered check reject a change.
- From AI code review that runs code (Greptile's TREX), seven packages in our strategy-adoption
  specification: map a change to the behaviours it can affect, one question per investigation,
  automatic confirmation, evidence in the pull request, one budget across models and replays,
  scoped memory of team feedback, and an optional read-only import of Greptile's findings. Their
  status is in [discovery.md](discovery.md#whats-next); none is claimed to help until it is measured.

**Four assertion types.** Enough for falls, missing textures and layering, not for timing or UI.

Next: timing ("within N frames"), counts, contact between objects, state changes, UI text that fits
its box, and audio cues.

## Judging what it sees

**The observers are measured on one art style.** SAM 3.1 finds the robot and the coins in this
game's pixel art on every clean frame, but it does not see the ground at all, and "small robot"
also matches the enemies ([docs/sam.md](sam.md)). Muse Glimmer's boxes are too loose for the ground
check ([docs/open-weights.md](open-weights.md)). The engine's position log covers what the models
cannot, but only for objects the harness logs: the robot and the coins, and since October 30 the
robot's facing, the enemies and the bullets.

Next:
- Score the observers against the position log on each new art style before trusting their verdicts.
- Run the engine-record checks (`agents/trace_checks.py`) in the verifier, after a natural-catch
  trial and a false-alarm run on the private routes.
- Log more objects from the engine, so a check about a door or a moving platform is not needs-review.
- Keep the rule that a missing or uncertain object means "needs review", never a pass.

**Determinism is proven on one setup.** Ten replays were bit-identical on a Linux machine with no GPU
and software rendering. Still untested: GPU rendering, multithreaded physics, network play, and
randomness the game does not seed.

Next: replay every failing route several times before reporting it, flag routes whose results
change between runs, and keep a baseline per platform. Since November 9 `agents/stability.py` does
this in the overnight loop and the held-out bench behind `--stability`, off by default
([harness.md](harness.md#flaky-routes-and-baselines-november-9)); the verifier still replays each
route once, and the only baseline is from the machine it was built on.

## Fixing

**Fixes are small and local.** The seeded bugs are one-line regressions, and the fixer gets a short
budget for small patches.

Next: multi-file fixes, a root-cause note in the morning report, and a link to the commit that
introduced the bug.

**The fixer starts from a plain report, and the evidence helps it on the subtle bugs.** Since
October 30, Muse Code gets Expectrail's evidence after a failed attempt
([report-first.md](report-first.md)). Across every live run, both held-out runs included,
report-only first attempts fixed 57 of 63 cases (90%) and evidence-first ones 39 of 42 (93%).
Every first-attempt miss under either briefing was a sinking bug. Since October 31, a timeout escalates to the evidence
too; that rule has not run live yet.

Next: run the Fix matrix's `escalate` condition on harder bugs, ones that span several files or
whose obvious fix is wrong, where a first attempt fails often enough to measure the second.

**"Accepted" means it passed our suite, not that the game is correct.** The held-out variants are
bugs we seeded ourselves.

The mutation bench measured how weak, on single edits nobody wrote: weighted by how common each
kind of edit is, the checks caught 0.9% of those that differ from the clean game, and none of the 45
in the sample that move, resize or re-layer something (10 of 77 over the sample as drawn;
[bench/mutation](../bench/mutation/README.md#results)).

Next:
- Reproduce real, historical bugs from open-source Godot games and compare Expectrail's fix with
  the one the maintainers shipped. A log of 200 candidate records, with the selection rules committed and
  27 first-pass survivors showing strong evidence of AI involvement, is waiting for a person to select from
  ([bugs/reported/candidates.md](../bugs/reported/candidates.md)).
- Publish each of the mutation bench's 67 survivors with the check that would have caught it, as
  #127 asks: they have findings but no catch-specs yet. Start with the code and missing-file
  survivors and the sprite drawn 26 px off the player's body; decide whether scenery should have a
  check at all.
- Longer gameplay routes, with a person keeping the final say.

## Running it for real

**Godot only, with a harness inside the engine.** Studios on Unity or Unreal can't use it, and some
teams can't add a harness to their build.

Next: harness adapters for Unity and Unreal using their fixed-frame-rate capture, plus a capture mode
that needs no engine changes, labeled as weaker on determinism.

**Scale is not measured.** On one level, a verified fix takes 12 to 22 minutes and about $3 of SAM
images ([`bench/demo-loop/`](../bench/demo-loop/README.md)); nobody has run it on a real project's
worth of routes.

Next: run routes in parallel on cloud machines without GPUs, sample frames instead of sending every
one, and skip routes a change cannot affect.

**It runs from GitHub Actions workflows and the command line, on our repository.**

Started after the event: a CI gate a Godot repository can add ([ci-gate.md](ci-gate.md)), the Greptile
adoption's G04. One job runs the pull request's game. A separate trusted job posts the verdict and
evidence as one pull request comment, whose finding ids stay the same across pushes. Its comment half
runs only from the default branch, so it has not run end to end yet.

Next: run the game inside a sandbox in the gate's verify job, so a pull request's code cannot rewrite
the evidence; export to issue trackers; and release pipelines that check a release candidate's
signature before shipping it.

**The trust test is one planted instruction plus a canary probe.**

Next: a set of poisoned assets instead of one, stronger default network denial inside the fixer
sandbox on every host (not only when bwrap/docker is present), and provenance for every artifact a
night produces.

## Beyond games

The north star is any change an agent makes to any software, verified by something the agent does
not control. We have built and measured game repairs, and one web page as a second domain
(below). What we expect to carry over, and what would have to be rebuilt:

| Part | Carries over? |
| --- | --- |
| The agent cannot reach the checks, the held-out cases or the signing key | Yes: it is a property of where things are mounted, not of games |
| Evidence comes from running the changed software, not from the diff or the agent's account of it | Yes, given a way to run the software the same way every time |
| A person approves each check, written as one plain sentence and drafted by a model | Yes |
| Discovered checks advise until a person approves them and they pass validation | Yes: a policy, not a property of games |
| Generic probes and a profile of claims read from the code | Partly: the probes, the profile and the trace signals are this game's; claims read from code, templates with no model, 3-of-3 reproduction and the clean control are not |
| Held-out cases the fixer never sees, and a clean control that must not raise a false alarm | Yes |
| Acceptance signed outside the agent's reach, checked before release | Yes |
| A missing or uncertain observation is "needs review", never a pass | Yes |
| The Godot harness and its exact-tick replay | No: each kind of software needs its own way to replay |
| Vision checks on game frames, and the engine's position log | No: these are this domain's evidence |

The closest next domain was a web interface, and we have built one, a checkout page, as supporting
evidence ([`apps/checkout`](../apps/checkout); results in the README's "Beyond games").

- **What was reused.** The evaluator, the contracts, the decision rule, the fixer and its sandbox,
  and the judge were reused unchanged.
- **What was rebuilt.** As the table above predicts, the rebuilt parts were the replay and the
  domain's evidence:
  - Chromium replays a recorded checkout session, as the Godot harness replays a route
    ([`harness/web`](../harness/web)).
  - The page's layout boxes stand in for the engine's position log.
  - Whether the order went through stands in for the gameplay check.
  - One rule the game did not need: a page is full of look-alikes (a blue badge beside a blue
    button), so a SAM box counts only where it overlaps the page's paint box for that element. A
    score threshold alone was tried first and rejected a correct fix.
  - Running the repair loop live found two faults the bench alone had not: a threshold that rejected
    a correct fix, and a tolerance too tight for SAM's box at a private screen size. Both are fixed,
    and the live matrix then accepted Muse Code's fixes for all 8 bugs.
- **What it does not yet have.** Held-out web bugs written by a person: the four it has were written
  by a separate agent that never saw the checks, and SAM caught all four. It also has no checks
  written by anyone outside the team.

Further out are backend and infrastructure changes, where the evidence is logs, metrics and
responses rather than pixels. None of that is built.

## Helping

To work on any of these, open an issue that names the section.
