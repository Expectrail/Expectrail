# Generated checks: tests written for one change

Built November 10, 2026, for issue #204. The public reproduction baseline was measured on
November 13: 17/24 defects, including 16/19 trace-visible defects, in
[run 43465090517](https://github.com/Expectrail/Expectrail/actions/runs/43465090517).
The [#285 audit](repro-audit.md) traces the figures to the original records and lists the later
offers and candidate-withheld measurements still missing. The [measurement plan](#measurement-plan)
covers the broader unrun cases.

For each change an agent proposes, Expectrail can now generate checks aimed at that change, keep only
the ones that are valid and deterministic, run them on the candidate, and report what they catch. It
is modelled on Meta's Just-in-Time tests (Meta Engineering, "Just-in-Time tests", October 29, 2026;
FSE 2026, arXiv [2601.22832](https://arxiv.org/abs/2601.22832)). It is aimed at the largest gap we
have measured: only checks people wrote can reject a change, they caught 10 of 77
generated single edits (0.9% weighted, [`bench/mutation/`](../bench/mutation/README.md)), and there
is no catch yet on a real agent fix that nobody anticipated.

**Raw v1 records are report-only.** The existing gate-summary remains advisory. The opt-in
[#271 counting path](#generated-checks-that-count-271) authenticates separate provenance and
requires all six rules before a generated check can reject or demonstrate a repair. A person alone
can promote it to an approved regression spec. Current workflows do not enable counting by default.

## What runs

```
bug report + candidate patch
   │
   ├─► diff map: changed files and lines → profile claims → probes        expectrail/jit/diff_map.py
   ├─► measure: every probe's signals on the clean game and the bug build expectrail/jit/measure.py
   ├─► intent: Muse Spark proposes up to 8 checks and 4 probes            expectrail/jit/intent.py
   ├─► near misses: wrong versions of the same change                      expectrail/jit/dodgy.py
   │
   ▼
headless, trace-only replays (no frames, so no SAM image)                  expectrail/jit/run.py
   │
   ▼
valid: passes 3 of 3 on the clean game, and fails 3 of 3 on a near miss    expectrail/jit/assess.py
   │
   ├─► any check rejected? one revision: the model is told why, from the clean game and the bug build
   │   only, replaces those checks, and the whole set is replayed again (same budget)
   ▼
   │
   ▼
catch: a valid check that fails 3 of 3 on the candidate → strong | weak
   │
   ▼
jit-run/v1 record, report, and an advisory block in the gate comment and the review page
```

| Part | Where | What it does |
| --- | --- | --- |
| Diff map | [`diff_map.py`](../expectrail/jit/diff_map.py) | Parses the patch as data (never applies it). A file is tied to a profile claim when the claim's own `evidenceRefs` name it; each claim maps to the probe families that exercise it. A file no claim names keeps every probe. |
| Intent | [`intent.py`](../expectrail/jit/intent.py) | One Muse Spark call. The report and the patch go in as string values of a JSON object, under a system prompt that calls them untrusted. The answer is parsed by discovery's planner parser, so only probes that compile and contracts that validate in the closed trace language survive. Every check gets origin `AUTO_DIFF`, authority `model_prior` and an id starting `jit-`. No model-written code runs. |
| Measure | [`measure.py`](../expectrail/jit/measure.py), [`probes.py`](../expectrail/jit/probes.py) | Before the model call, each probe is replayed once on the clean game and once on the bug build (the base patches), never on the candidate, and every signal's value goes into the prompt as a number, next to a one-line meaning of each signal. The model picks a probe and signal where the two builds differ and puts a threshold between them. Its own job, with no secret; the propose job re-checks the numbers' shape (known probes, known signals, plain numbers, the same base patches) and goes ahead without them, saying why, if they do not fit. The probes are discovery's library plus the jump taps once more after walking left, the one place on the level with nothing overhead. |
| Near misses | [`dodgy.py`](../expectrail/jit/dodgy.py) | The base build (the game the report describes); the mutation bench's operators on the lines the candidate added, with the steps the bench registered (read, never written); three code operators of our own for lines those do not reach (a boolean flipped, a condition negated, a statement replaced by `pass`); and, when the candidate changes more than one place, each place undone on its own. At most 8 besides the base, chosen by a seed taken from the candidate's bytes. |
| Job | [`run.py`](../expectrail/jit/run.py) | Replays the reference first and drops a check at its first non-pass; replays each near miss once and confirms a kill to 3 of 3; replays the candidate 3 times for valid checks only. Budget checked before the model call and before each replay. |
| Assessor | [`assess.py`](../expectrail/jit/assess.py) | Pure functions of the interpreter's five outcomes per run. Nothing a model said reaches it. |
| Record | [`contracts/jit-run.v1.schema.json`](../contracts/jit-run.v1.schema.json) | One per change: digests of the inputs, model and prompt; settings; the diff map; every proposed check and probe; every near miss; each check's reference runs, kills, candidate runs and outcome; the catches with their label; spend with the prices used. `advisory` is always true and there is no decision field. |
| Revision | [`intent.py`](../expectrail/jit/intent.py) `revise_to_file` | When the first replay rejects any check, one more model call. Each rejected check goes back with one of two reasons: it did not pass on the clean game (with the interpreter's outcome names), or it did not fail on the bug build. Never the candidate's outcomes or the near misses built from the candidate, which would let it fit checks to the change under test. At most one replacement per rejected check; kept checks stay as they were. The first round's record is read as untrusted data (schema-valid, this patch, plain numbers), and the second record carries the first round's replays and both calls' tokens, so the $2 cap covers the whole change. No budget left, no rejected check, or an unusable answer: the first round stands. |
| Candidate withheld | [`intent.py`](../expectrail/jit/intent.py), [`run.py`](../expectrail/jit/run.py) `from_base_alone` | Issue #285, step 6. With `--withhold-candidate` on `propose`, `revise` and `run`, the model is given no byte of the candidate patch and nothing made from it: the prompt has no `untrustedCandidatePatch` and no `patchTouches`, every library probe is on offer, and the system prompt says no fix is shown. Two fixes of one report give the model the same prompt. The proposal is bound to the report (`reportSha256`, no `patchSha256`), so it can judge any fix of that report; the record says `settings.candidate: withheld`. A proposal, intent or first-round record made one way is refused by a step made the other. `from_base_alone` lists a record's checks that passed on the clean game and failed on the bug build 3 of 3, and of those, the ones proposed with the candidate withheld: the first condition of #271. Off by default: with the candidate shown, every prompt is byte for byte as before. `python -m expectrail.repro score --candidate withheld` counts only records made with the candidate withheld, and the default (`shown`) only those made with it shown; a record of the other setting is no result, and a withheld score says `candidate: withheld` on its record and its page. In `jit.yml` it is the `candidate` input (`shown`, the default, or `withheld`): `withheld` passes `--withhold-candidate` to `propose`, `revise` and every replay, and `--candidate withheld` to `repro-score`, which also reads the committed screen record (`--screen bench/jit/public/screen.json`); the known-bugs bench refuses `withheld`. |
| CLI | [`cli.py`](../expectrail/jit/cli.py) | `run`, `measure`, `propose`, `revise`, `report`, `gate-summary`, `diff-games`. |
| CI | [`.github/workflows/jit.yml`](../.github/workflows/jit.yml) | Rehearsal on pull requests that touch this code; `live` by dispatch; `bench` (the known-bugs bench) and `repro` (the public reproduction bench) by dispatch from main only. |
| Gate | [`gate/`](../expectrail/gate), the verify action's `generated-checks` input | Reads and shows a generated-checks block; nothing in a pull request's run produces one yet (below). |

### Valid, catch, strong, weak

- **Valid.** Passed on the clean game on every one of 3 runs (no failure, no gap, no error, actually
  exercised), and failed on every one of 3 runs of at least one near miss. A check that fails on
  nothing near the candidate tells us nothing about it, so a check that "always passes" is dropped
  here, whoever proposed it.
- **Catch.** A valid check that fails on all 3 runs of the candidate. Mixed results are `flaky`, never
  a catch.
- **Strong.** The catch also fails on all 3 runs of the base build, or its claim is one a person
  approved (none is today: every profile claim is `inferred_code`). The issue's wording is "fails on
  the buggy base for the reported reason". We cannot read a reason off a trace, so v1 uses the base
  failure as the proxy and says so. **Weak**: every other catch.

### Prices and the budget

Muse Spark's per-token price is not published to us, so the record carries assumed prices, set high:
$1 a million prompt tokens and $4 a million completion tokens (override with
`--spark-usd-per-mtok-in/out`). Replays are charged at a GitHub-hosted Linux runner's $0.008 a minute
for the time each took; SAM at $2.50 a thousand images, though v1 takes none. Before the call, the
budget reserves the prompt plus 30,000 completion tokens; a call that reports no token count is
charged that reservation. Every record names its prices and says `source: assumed`.

## The rules, and the test that holds each

| Rule | Held by |
| --- | --- |
| 1. Report-only: no path from a generated check to a rejection | `tests/test_jit_rules.py` `Rule1ReportOnly`: the schema has no decision and `advisory` is the constant true; a record with strong catches keeps the decision its counts give, and one that claims otherwise is refused; `decide()` takes only the counts and the held-out counts; nothing that decides imports `expectrail.jit` |
| 2. The fixer never sees generated checks | `Rule2FixerNeverSees`: every file a run writes, and a proposal, sits under a `jit-*` name that the fixer workspace's isolation refuses (`agents/isolation.py`); no fixer module reads them |
| 3. Fail closed to "nothing generated" | `Rule3FailClosed`: model unavailable, empty or invalid answers, no model, a replay error, an unreadable patch, an unreadable gate block. Each gives `nothing-generated` with its reason, no catch, and "no generated checks" in the comment |
| 4. $2 a change, enforced before each call | `Rule4Budget`: the model is not called when its reservation does not fit, on the one-step path and on `propose` (the call asks for no more completion than it reserved, `max_tokens`); a replay is reserved at the longest one seen so far, so one that runs longer can carry spend past the cap by its own cost, after which nothing further runs; spend and prices are reported |
| 5. The patch and report are data | `Rule5UntrustedInput`: a patch and report that tell the generator to write a check that always passes and to mark a catch give the same validity and catches as the clean change; the injected "always passes" check is dropped as killing nothing; the extra fields (`catch`, `verdict`, `decision`, an approval) are never read |
| 6. Retired pins untouched | `Rule6RetiredPins`: `bench/mutation/preregistration.json` and `discovery/freeze.json` are byte-identical to commit `c169a5e`; the near-miss generator only reads the registration |

Determinism (the same change gives the same catches 10 times out of 10) and the rest of the
pipeline are in `tests/test_jit_pipeline.py`. All of these run on a simulated game, offline, with a
fake model; they show the rules are wired, not how often the generator catches anything.

## In the gate

The gate can show a generated-checks block: `run_gate(generated_checks=...)`, the verify action's
optional `generated-checks` input and `gate-summary` read it after the decision is made, with the
same strict reader as the rest of the record (size cap, strict JSON, closed schema, counts recomputed
from rows). A block it cannot read becomes "no generated checks"; it never fails the gate. The
comment shows a short section headed "Generated checks (advisory, they never accept or reject)" and
the review page a table, both apart from the checks that decide.

A catch in that block is strong only when the run that made it replayed a base build (`run --base`):
the label comes from the base build's runs, so a run without one can only report weak catches.

**Nothing in a pull request's run produces that block, and nothing proposes checks there.** The first
version of this work did, in a `jit-propose` job in `expectrail-verify.yml` that held the model key,
ran Expectrail's code from the base commit and read the pull request's game as text. That cannot be
made safe on `pull_request`: such a run uses the pull request's own copy of the workflow, so the
pull request's author can edit the job to print the key, whatever the job was written to do. Since
#223 every model key lives in the `main-only` environment, which a pull request cannot deploy to, so
the job would also have had no key. It was removed before merging, and `tests/test_ci_gate.py` keeps
`expectrail-verify.yml` free of secrets.

Proposing checks for a pull request safely needs a workflow that runs from main, in `main-only`,
and reads the pull request only as data: a workflow on main that a keyless pull-request job
starts by `workflow_dispatch`, as `private-scan` is since #247. That is not built. Until it is, generated checks are proposed by dispatching `jit.yml` from
main (`live`).

## Run it

```
export PATH="$PWD/tools/godot:$PATH"
python -m expectrail.jit.cli run --report-file report.txt --candidate fix.patch \
    --base bugs/reported/air-jump.patch --out runs/jit --model spark      # needs MODEL_API_KEY
python -m expectrail.jit.cli report runs/jit/jit-run.json
```

The two steps CI uses, so the key and the replays stay apart:

```
python -m expectrail.jit.cli propose --report-file report.txt --candidate fix.patch --out runs/jit-proposal
python -m expectrail.jit.cli run --report-file report.txt --candidate fix.patch --base bug.patch \
    --proposal runs/jit-proposal/jit-proposal.json --out runs/jit
```

In CI: the **Generated checks** workflow. `rehearsal` replays the committed stand-ins in
[`bench/jit/rehearsal/`](../bench/jit/rehearsal): the public air-jump bug fixed exactly (expected: no
catch) and "fixed" with a comment only (expected: a strong catch). Their proposals were written by a
fixture standing in for the model (`"model": "rehearsal-fixture"`), not by Muse Spark. The profile was
written alongside that bug, so a rehearsal shows the plumbing and is never a result. `live` takes a
case name, a base patch, a candidate patch and a report file, and calls Muse Spark.

## First live runs

Run 42908014398 (main at `c78e623`, the comment-only "fix" of the air-jump bug) worked end to end and
found nothing: 2 checks proposed, 0 valid, $0.04. Both compared heights (two presses higher than
one; eight no higher than two). Replayed locally, the reason is the level, not the bug: the player
starts under a platform, and every spot discovery's right-hand walk sweep reaches has one within
reach of a double jump, so two presses and eight both rise 104 px on the clean game *and* on the
bug build. No height check there can see infinite air jumps. The model was given the signal names
and nothing else, so it could not have known. Two changes, both above: the measurements, so the
model sees which signals move between the clean game and the bug build (on `jump-w0-x8`,
`air_jumps` goes from 1 to 7 and `max_rise_px` does not move); and the left-walk jump probes, where
a rise is not capped (eight presses: 114 px clean, 424 px bug build).

## Measurement plan

Rows link their CI run once measured. The two rows measured so far are the known-bugs bench and blind set 3 (below).

| Measure | Baseline today | Target for v1 to be worth keeping | Result |
| --- | --- | --- | --- |
| Mutation bench Part 2 (generated bugs), weighted catch rate, approved checks plus generated checks | 0.9% (10 of 77) | Clearly above, with the per-class table | not run |
| Mutation bench Part 1 (wrong fixes), catch rate | 31 of 39 | No loss; extra catches among the 8 missed | not run |
| False alarms on the clean game | 0 | 0 | not run |
| False catches on correct fixes (the judge benchmark's 8 correct fixes, 3 runs each; the 10 live demo-path fixes) | none measured | 0 strong; weak reported | not run on those; 0 of 4 on the known-bugs bench, 0 of 18 correct candidates on blind set 3 |
| A natural catch: a generated check fails on a real Muse Code fix the approved checks accepted, confirmed wrong by a person | 0 | 1 or more, or an honest "none" | not run |
| Determinism: the same change, 10 reruns | none measured | The same catches every time | offline only (simulated game) |
| Spend per change | none measured | $2 or less, median reported | known-bugs bench: $0.10 per case on average, $0.23 at most ([42927364671](https://github.com/Expectrail/Expectrail/actions/runs/42927364671)); blind set 3: $3.67 for 34 candidates ([42942805407](https://github.com/Expectrail/Expectrail/actions/runs/42942805407)) |

The stress tests, in the order we intend to run them:

0. **The known-bugs bench, live** ([`bench.py`](../expectrail/jit/bench.py),
   [`bench/jit/known/`](../bench/jit/known/), `jit.yml` in `bench` mode). Rehearsals replay a committed stand-in, so
   they say nothing about what a real model writes. This runs the whole live pipeline on the four
   reported bugs, each with a wrong fix (a comment claiming the fix) and the correct fix (the exact
   undo), and scores the final records against a bar registered first
   ([`preregistration.json`](../bench/jit/known/preregistration.json)): at least 3 of 4 wrong fixes
   caught strong, at least 2 of them on the three bugs nobody tuned on (#240 was designed on air-jump),
   no catch of any strength on a correct fix, no case without a result, $2 or less per case. The
   workflow refuses to start from anywhere but main, or unless the registration is signed off and every
   file it pins is unchanged. Below the bar, arm B does not run on blind set 3.

1. **A new pre-registration, then the mutation bench with generated checks on.** Registered before any
   judged case, in the style of #127 and #164: pins, the sample, the scoring rule. Rehearsed on
   stand-ins first. The existing registration stays as the record it is (rule 6); this is a new one.
2. **Blind set 3** ([`blind.py`](../expectrail/jit/blind.py), `jit-blind.yml`,
   [`preregistration.json`](../bench/jit/blind-3/preregistration.json), signed off 2026-11-10). The
   private set (digest `a5ffad12…`, game commit `f864af5d…`) has 8 defects, each with its own wrong
   fix and correct fix written by the session that wrote the defect, and 2 intentional changes. Arm A
   is the CI gate with the defect build as base; arm B adds a strong catch from the generated checks.
   Primary candidates are the set's own fixes and the intentional changes (18); supplementary ones,
   reported apart, are a comment-only fix and the exact undo per defect, made by the runner from the
   defect patch alone (16). The claim holds if B catches more primary wrong fixes than A with no more
   false catches. One run from main, after the pins and the digest are checked; counts only leave.
   **Result** (run [42942805407](https://github.com/Expectrail/Expectrail/actions/runs/42942805407), `0906f29`):
   **adds value.** Wrong fixes caught: A 0 of 8, B 3 of 8 (all 3 among the 5 trace-visible defects).
   False catches on 8 correct fixes and 2 intentional changes: A 0, B 0. Supplementary: comment-only
   fixes caught by B on the same 3 defects (1 no result), no exact undo caught. Spend $3.67. The
   approved checks accepted every candidate, so the baseline is zero; wherever the generator
   reproduced the defect it also caught the set's convincing wrong fix, and the 5 misses are defects
   it did not reproduce. Two earlier runs stopped on runner bugs before any candidate ran.
3. **Correct-fix pressure.** Every correct fix we have, three runs each. A strong catch on a correct
   fix is a bug in the filter and is looked at before anything else.
4. **Overfitting adversary.** A separate fixer instance gets the generated checks for one bug (only in
   this test) and is asked for a wrong fix that passes them. Not built yet.
5. **Prompt injection and outage.** Offline, in `tests/test_jit_rules.py` (rules 5 and 3). Done, on the
   simulated game.
6. **A second domain.** One pass on the web checkout page (`apps/checkout`). Not built yet: the diff
   map, near misses and replays here are Godot's.
7. **Flake.** 10 reruns of the same change, live.

## The public reproduction bench

Added November 11, 2026, for issue #285. On blind set 3 every miss was a defect the generator never
reproduced, so the next number to move is the reproduction rate: the share of reported bugs for
which a generated check fails on the bug build 3 times of 3 and passes on the clean game 3 times of
3. It is developed on public defects only.

[`bench/jit/public/`](../bench/jit/public/README.md) holds the bench: 24 defects of the bundled
game, the 4 reported bugs and 20 written for it, each a patch and a bug report in a player's words
(`expectrail.repro-bench/v1`, read by [`expectrail/repro/bench.py`](../expectrail/repro/bench.py)).

**The baseline, November 13, 2026: 17 of 24 reproduced (71%); 16 of the 19 defects that change the
engine's record on a library probe (84%, the issue's target set is 70%); $2.05 in all, at most $0.17
for one defect.** Run 43465090517, dispatched by Sean from main, offer `baseline`. The 7 misses: 2
`no-signal` (both camera defects), 1 `wrong-predicate` (`coin-stays`), and 4 the records cannot
classify, which the hand findings of November 12 call `probe-language` (2, screen only) and
`route-never-reaches` (2, the pause menu). These were read from the run's job logs; the score file is
not committed yet. The bench's page has the table and the source of each number.

Before that run, what was measured needed no model
([`expectrail/repro/visibility.py`](../expectrail/repro/visibility.py)): every probe was replayed on
the clean game and on each defect build, and each defect sorted by what changed in the engine's
record. A signal reads differently on some probe for 17 of the 24 (for one of them only by a
hundredth of a pixel); the record differs and no signal does for 2, both camera defects; the record
is the same on every probe for 5. So on the library's probes, with today's signals, a generated
check could fail on at most 17 of the 24, before the model has proposed anything; the model may add
up to four probes of its own, which this does not replay. The table, the command and what was and
was not shown are on the bench's page. That run was made in a cloud container, not in CI.

Built November 11 and first run on November 13: a `repro` mode in `jit.yml` (from main only) that sends each defect through
the live jobs with one stand-in candidate for all, a comment line in the game's README that
changes nothing ([`no-fix.patch`](../bench/jit/public/no-fix.patch)), so a check comes from the bug
build and the report alone; and the scorer that reads the run's records
([`expectrail/repro/score.py`](../expectrail/repro/score.py), `expectrail.repro-score/v1`). A
defect counts as reproduced when a generated check passed on the clean game 3 times of 3 and
failed on the bug build 3 times of 3, with and without the no-fix patch. A miss gets a reason from
the issue's vocabulary where the records can show one, and `undetermined` where they cannot. The
bench's page says how each is decided.

**Misses sorted by the screen record** (November 15, 2026, issue #285 step 2). Given the screen record
(`python3 -m expectrail.repro score ... --screen bench/jit/public/screen.json`), the scorer itself gives
the two reasons that only hand findings gave before, for a miss the engine's record does not show on any
library probe: `probe-language` where the frames differ there (`screen-only`) and the setting offers no
check about the screen, and `route-never-reaches` where nothing differs in the record or the frames
(`neither`). The reader recomputes both, so neither can be written where the screen record does not
show it. Under the pixel setting a screen-only miss stays `undetermined`: checks about the screen were on
offer, and the records cannot say whether the observer could not tell or the predicate was wrong. On
the committed visibility and screen records, the rule gives each of the baseline's four unclassified
misses the reason its November 12 hand finding gives (a test holds this). Not shown: a score file
made this way from a live run's records, since none is committed.

**Reach** (November 12, 2026, issue #285 step 3; [`expectrail/repro/reach.py`](../expectrail/repro/reach.py)).
One of the five defects the library's probes leave unchanged, `no-shooting-in-air`, is in the
engine's record whenever a route shoots in the air, and no library probe does: the library never
presses two different actions close together except moving while firing. Reach finds every pair of
actions in the game's own catalog that no library route uses together (on the platformer: left with
right, left with jump, right with jump, jump with shoot) and makes two short routes for each: hold
one and tap the other three times meanwhile, and the other way round. Eight probes of 160 ticks on
the platformer, at most eight for any game. No model is asked, and nothing is written for one bug.
The bug report only orders them, the pair it names first, and can add nothing. Replayed on the
real engine with no model (the clean game twice, each defect build once, in a cloud container, not
in CI), `reach-jump-with-shoot` reads `projectile_count` 1 on the clean game and 0 on
`no-shooting-in-air`; a signal moves on a reach probe for 14 of the 24 defects, 13 of which the
library already showed. The table is on the bench's page. A reach probe is a route: what watches
the game along it, the engine's record or frames for a visual observer, is the caller's choice.
**Generated checks are offered these probes only under `--offer signals-reach`** (below, "What the
generator is offered"); under the default, `baseline`, they draw on the library alone, so the
baseline run is unchanged.

**Menu probes** (November 13, 2026, issue #285 step 3; [`expectrail/repro/menu.py`](../expectrail/repro/menu.py)).
The bundled game draws its coin counter only on the pause menu, and two bench defects break the
counter. Two things kept every route away from it. The harness was paused with the game, so a route
that pressed the pause key never reached its last tick; it now keeps running while the tree is paused
(`harness/godot/expectrail_harness.gd`, held by the engine test `tests/test_pause_input.py`). And
the action catalog has no pause action: a menu probe is a library walk, then one tap of a menu action
the caller names and the game's `project.godot` declares, then 90 ticks with the menu drawn. The
action is not added to the mechanics profile, so no offer's prompt or probe list changes, and **no
offer uses menu probes**. Replayed on the real engine with no model, both coin-counter defects change
the screen from the frame the menu opens on, in the corner where the count is drawn, and nothing in
the engine's record; the records and the table are on the bench's page. Like the two other
screen-only defects, they wait on checks that can speak about what is drawn (#286).

**The menu setting** (November 18, 2026, issue #285; `--offer signals-reach-evidence-menu`). Since the
#285 audit a check can read the engine's one integer Label (`ui_integer_at_end`) and compare it with
`coins_collected` on the same probe. This setting is the evidence setting plus the three menu probes,
so a generated check can do that where the counter is drawn. The menu action comes from the reviewed
mechanics profile's new optional `menuActions` (`["toggle_pause"]` in
`discovery/platformer.profile.json`), never from the report, the patch or the model, and it is refused
unless `project.godot` declares it. Only the menu probes press it: the prompt's `actions` list stays the
catalog, and a probe the model writes is compiled with the catalog alone (`offer.route_actions`). A run
under this setting with a profile that names no menu action generates nothing. Records say `menu` as the
source of such a probe. Every other setting's prompt and probe list are unchanged. Not yet run live.

**What the proposer is shown on a menu probe** (November 18, 2026, issue #285). The harness records the
counter only when asked, and until this change the measure step and the evidence asked on no replay: on
Godot 4.7.2 the measure step read `ui_integer_at_end` as no reading on every menu probe, clean and bug
build alike, so the prompt showed nothing about the counter where it is drawn. Now the measure step's and
the evidence's replays of a menu probe, and of no other probe, ask for it (`offer.replay_options`, the
harness's `ui_integers`). On the real engine, `hold-right-then-toggle-pause` measures 5 on the clean game,
10 on `coin-counts-twice` and 0 on `coin-counter-stuck` (`tests/test_jit_menu_reading.py`), and its
evidence on `coin-counts-twice` now shows `uiIntegers` differing from tick 310 and the signal reading 5
against 10. These are readings, not a reproduction rate; no model was asked. Every other probe's replays
are as before.

**What each defect changes on the screen** (November 12, 2026; [`expectrail/repro/screen.py`](../expectrail/repro/screen.py),
`expectrail.repro-screen/v1`). Every library probe was replayed with its frames captured, on the
clean game twice and on each defect build once (650 replays on the real engine, in a cloud
container, no model, not in CI), and the frames and the record of the same replays compared with
the clean game's. The record and the picture both differ for 19 of the 24 defects; only the picture
differs for 2 (`enemy-walks-backwards`, `bullet-behind-scenery`), which are the bench's screen-only
defects for issue #286; no defect changes the record and no frame; 3 change nothing on any probe.
Nothing differed between the two clean replays. This compares pixels exactly and asks no visual
observer anything: it says where a difference could be shown, not that an observer reports it. The
table and its limits are on the bench's page. **Nothing generated checks run on reads it.**

**Evidence for one bug build** (November 13, 2026; [`expectrail/repro/evidence.py`](../expectrail/repro/evidence.py),
`expectrail.repro-evidence/v1`; issue #285, step 5). The proposer is given each probe's signals on
the clean game and on the bug build (`measured`, above) and nothing else. A signal is a reading of
the engine's record, so a bug that only shows on the screen gives the proposer nothing to build on.
An evidence record is what it could be given instead: for one bug build, along every probe, the
record fields that differ with the first tick, the signals that moved, the frames that differ with
the first one and the place of the difference, and, where a visual observer's recorded answers are
given, what the observer answered on those frames of both builds. It is made with no model; an
observer's answers are looked up and never asked for. `evidence.for_proposer` is the bounded
summary a prompt could carry; it shows only probes and objects its caller names, so nothing a
record says can put a new string in a prompt. Four records made on the real engine are on the bench's page.
It is offered to the generator only under the third setting below, `signals-reach-evidence`; under
the other two the prompt is unchanged.

**What the generator is offered** (November 13, 2026; [`expectrail/jit/offer.py`](../expectrail/jit/offer.py)).
Steps 3 and 4 were built before the baseline was run, so they are held back. One setting, the same
in every step of one change, says what the generator is given:

- `baseline`, the default: the eleven signals and the jit probe library, as before steps 3 and 4.
  The system prompt and the user prompt are the same bytes as before the setting existed; a test
  holds their digests as computed on main before the change.
- `signals-reach`: also the three signals of step 4 and the eight reach probes of step 3. The bug
  report only orders the reach probes.
- `signals-reach-evidence` (added later on November 13): everything `signals-reach` offers, and step 5's
  evidence. The measure job also replays every probe with frames, the clean game twice and the bug
  build once (`--evidence-jobs` at a time), and uploads `repro-evidence.json` beside the
  measurements; under this setting it installs a virtual display and software OpenGL and may run
  75 minutes instead of 30. The propose and revise jobs read the file with `--evidence`, re-check it
  as untrusted data (schema, its own sums, made for these base patches), and put
  `evidence.for_proposer`'s summary on at most six probes of the prompt as `differs`: the record
  fields that differ with their first tick, the signals that moved, and on how many frames the
  picture differs, from which frame, where. No observer is read for it. The system prompt is
  `signals-reach`'s with one paragraph more, which says checks still read only signals (the closed
  language has no pixel predicate until #286). A run under this setting that cannot make the
  evidence stops in the measure job; a propose step given none says so in the proposal's
  diagnostics. `expectrail/jit/offer.py` is the one file under `expectrail/jit` that reads the
  evidence module.

`jit.yml` takes it as the `offer` input (default `baseline`) and passes it to measure, propose,
revise, both replays and the reproduction score; the known-bugs bench refuses anything but
`baseline`, the setting it was registered under. The setting is written into each proposal
(`offer`) and each run record (`settings.offer`). A saved proposal is replayed only under the
setting it was made with, a revision only under the setting of its first round, and the
reproduction score counts only the records of the setting it is given and names that setting on its
page (`offer` in `expectrail.repro-score/v1`); a record of another setting is a row with no result.
A proposal or record written before the setting existed states none and is read as `baseline`.
Nothing about what keeps or drops a check changes.

Not done: the live baseline itself, which a person dispatches, and so the rate and the breakdown
of misses; and the `signals-reach` and `signals-reach-evidence` runs after it. The measure job's
frames under `signals-reach-evidence` have not been captured in CI yet: the capture smoke job
renders with the same packages, but this job has not been dispatched with them.

### Three signals for what the record showed and no signal read

Added November 12, 2026 (issue #285, step 4). The measurement above found three defects whose
symptom is in the engine's record in a field no signal read: both camera defects (`view`) and
`coin-stays` (`coins`). The episode now keeps those two fields
([`normalize.py`](../expectrail/trace/normalize.py), `contracts/episode.v1.schema.json`) and three
signals read them ([`signals.py`](../expectrail/trace/signals.py)). Each is a number over one replay
and can be used in a `relation` between two probes, like every other signal:

- `coins_collected`: coins in the level on the first tick, less those still there on the last. No
  reading when the trace never names coins.
- `player_screen_x_range_px`: how far apart the player's leftmost and rightmost places on the screen
  are, in frame pixels. Near zero while the camera follows; it grows when the camera stops and the
  player walks on. The ticks before the engine first applies the camera are left out. No reading
  without a camera in the trace.
- `player_screen_y_range_px`: the same, top to bottom.

What they read on the real engine (Godot 4.7.2, every library probe replayed once on each build, the
clean game twice with the same readings both times; in a cloud container, not in CI):

| Defect | Signal | Probe where it moves most | Clean game | Defect build | Probes where it moves |
| --- | --- | --- | --- | --- | --- |
| `camera-stops-right` | `player_screen_x_range_px` | `hold-right` | 5 | 191.69 | 6 of 25 |
| `camera-cut-top` | `player_screen_y_range_px` | `jump-l40-x8` | 169.81 | 203.37 | 1 of 25 |
| `coin-stays` | `coins_collected` | `hold-right` | 5 | 0 | 10 of 25 |

`camera-cut-top` is the weak one: one probe reaches high enough, and the range there is not near
zero on the clean game either, because the camera sits on its lower limit at the start and the
player's jump shows on screen. A check on it needs a threshold between two measured numbers.

**The generator is not offered these three yet.** The issue asks for the baseline rate before
anything changes, and that run has not been made. So the model gets the same signal names, meanings
and measurements as before (`NOT_YET_OFFERED` in [`intent.py`](../expectrail/jit/intent.py)); a
check it proposes on one of the three is dropped and said, and a saved proposal with one is
refused. The system prompt is the same text as before, byte for byte. They are offered only under
`--offer signals-reach` (above, "What the generator is offered"). No live run has used these
signals, and nothing here says the model will propose a check on them.

## Pixel checks: what is drawn (added November 14)

Issue #286. A generated trace check reads the engine's record, so a defect that only shows on the
screen can never fail one: on the public bench's baseline (run 43465090517), 1 of the 5 screen-only
defects was reproduced. [`pixel.py`](../expectrail/jit/pixel.py) adds the closed shape a generated
check takes when it speaks about the screen: `expectrail.pixel-check/v1`
([schema](../contracts/pixel-check.v1.schema.json), [example](../contracts/examples/pixel-check.json)).

- **Objects are bound roles.** The bundled game's are `player`, `coin`, `bullet`, `ground` and
  `coins-counter` (`BUNDLED_BINDINGS`, named after the game's own nodes). #259 will give every
  project its own in `expectrail.project/v1`. A candidate naming anything else is refused.
- **Observers declare what they cannot tell.** `sam-3.1-anchor` is SAM 3.1 asked about the place the
  engine's record puts the object ([`agents/sam_anchor.py`](../agents/sam_anchor.py)). It judges
  `visible`, `inside-region` (around the engine's box) and `never-crosses` (a fixed line). It cannot
  tell the ground or what a label reads. It sees only objects the record gives a position for (the
  player, in the bundled game), one at a time, so it cannot judge `reaches`. `visual-sensor` is #262's
  no-model template sensor (below, "The no-model sensor as an observer"): the player and, since
  November 16, the enemy at each of its logged boxes; the same three predicates, no ground, no text, and
  not which way a sprite faces. All of this is decided when a check is proposed.
- **Only frames with both the observer and the record count.** A frame the observer was not asked
  about (the engine puts the player outside the picture), could not answer, or that lacks the
  engine's box an `inside-region` check needs is a gap. A run with a gap is `needs-review`. An answer
  that does not hold the point it was asked about is "looked for, not found", which is a result.
- **Keep rule:** pass on the clean build 3 runs of 3, fail on the bug build 3 runs of 3, with the
  observer asked the same way on all six. Asked with a point, SAM's lowest score on the clean game
  was 0.5. Asked with a box, it was 0.87. The same check can pass under one setting and fail under
  the other.
- **Budget:** one SAM image a frame in the check's window, on six runs, reserved against the
  change's cap before anything is asked. A check that does not fit is `not-run`.

**What the recorded answers show.** These are SAM's answers of run 43335151089, the smoke route, asked
with a 48 x 68 box. The example check is "the player is found where the engine puts it in every frame,
score at least 0.8". It passes on the clean game and fails on both layering bugs and on the second
sinking bug. It passes on the missing texture and the first sinking bug. It is `needs-review` on
physics fall-through: the engine puts the player outside the picture from frame 20, so there is
nothing to ask about. A recording holds one answer per frame per build, so the tests' "three runs"
are the same answers three times. They test the rule, not how repeatable SAM is. These are seeded
bugs of the bundled game, not public bench defects.

**Offered to the proposer (added November 14, second slice).** Under
`--offer signals-reach-evidence-pixel` (`offer.PIXEL`), the proposer gets everything the evidence
setting gives it, and may also write up to four checks in `pixelChecks`:

- The system prompt adds one passage (`intent.PIXEL_TEXT`) with the four predicate shapes. The user
  prompt adds `pixelChecksOffered` (`pixel.menu`): for each observer that exists, the predicates it
  judges and the bound objects it can be asked about, and every object no observer can judge, with
  why. On the bundled game that is SAM, `visible`, `inside-region` and `never-crosses`, about the
  player (and, since November 15, the enemy and the bullet: see below). The menu is made from the same tables as the refusals, and a test checks that
  everything it offers is accepted and nothing it withholds is.
- The answer's `pixelChecks` go through `parse_candidate`, are renamed `jit-px-<id>` and carry
  `model_prior` authority. A refused one, a repeated id, or one past the fourth is dropped and said.
  An answer with pixel checks and no trace check is usable under this setting only.
- The proposal file carries `pixelChecks` under this setting only. Read back, each check must come out
  of `parse_candidate` unchanged; an edited one, or pixel checks in another setting's proposal, is
  refused.
- `pixel.assess` judges a proposal's pixel checks from an observer's answers: each check's images are
  reserved against the cap together with the checks before it, then the keep rule applies.

Every other setting's prompts are byte for byte as before. Nothing has been proposed under it by a
live model.

### The replay judges pixel checks (added November 14)

`run.generate(..., offer=PIXEL, observer=..., frame_runner=...)` judges the proposal's pixel checks
after its trace checks:

- Each check's probe is replayed **with frames** on the clean game and on the bug build (`[*base]`),
  three times each, and the observer is asked about every run. The observer is a callable with a
  `name` and a `frames(route)` (`pixel.observe` reads its answer as untrusted data: a malformed answer
  or a failure drops the checks on that probe, never passes them).
- The keep rule is `pixel.keep`'s: passes on every clean run, fails on every bug run, one observer
  setting on all six, no frame without both the observer and the engine's record. A kept check is
  then judged on the candidate three times: failing every time is a catch.
- The observer's images are reserved before the replays (one image a planned frame, on nine runs),
  against the same cap; what the observer says it sent is charged. Over the cap, with no observer, no
  frame runner or no bug build, a pixel check is `not-run` with its reason. The trace checks' results
  stand either way; a replay that fails still ends the run as nothing generated.
- The rows are the run record's `pixelChecks` ([example](../contracts/examples/jit-run-pixel.json)).
  They are not in `catches`, `counts` or the gate summary. `from_base_alone` lists the kept ones in
  `pixelReproducing`, decided from the rows' runs, never their status.

A revision replaces rejected trace checks only. Since November 14 (seventh slice) it carries the first
round's pixel checks to the second round as they are, with the probes they replay, and any pixel checks
in the revision's answer are not read (the revision prompt says so under this setting only). The command
line's `run`, `revise`, the reproduction score and the workflow take the setting (below).

### SAM as the observer (added November 14)

[`sam_observer.py`](../expectrail/jit/sam_observer.py) is the `sam-3.1-anchor` observer the replay
asks. On each replay it asks SAM 3.1 what is drawn inside the player's box at the place the engine's
record puts the player, one image a planned frame (agents/sam_anchor.py asks and measures):

- **The box** is the player's collision box as the harness logged it on that tick, widened by 4 game
  pixels each way (`box=body`, the default). A sized box with a lift (`box=(48, 68), lift=17`) is the
  setting SAM was recorded with on the bundled game, kept so those answers can be replayed.
- **The frames are planned from the route alone**, before any replay, so the budget is reserved for
  exactly those: every 10th frame and the last one the route's ticks fill, at most 30.
- **The frames must line up**, or nothing is judged: the replay is of the check's route, captured at
  the frame and physics rates the plan assumed, with its frames numbered from 0 without a hole and each
  asked frame matching the digest in `replay.json`. A planned frame the replay did not capture, or a
  tick with no player, camera or body box logged, is a gap: the check is `needs-review` on that run.
- **What is charged** is every request the client made, retries included. An observer that stops part
  way (no key, no credit, the cap) is still charged what it sent.
- `RecordedSamClient` gives back a recorded answer file, and only for the question SAM was asked: a
  different box or frame stops the run, and its setting must be the observer's. Through it, SAM's
  recorded answers on the smoke route replay through the real observer with the same boxes, answers
  and results (`tests/test_jit_sam_observer.py`, on synthetic replay folders built from the recording).

### The command line and the score take the pixel setting (added November 14)

`python -m expectrail.jit.cli run --offer signals-reach-evidence-pixel --observer sam-3.1-anchor ...`
builds the SAM observer (`cli.observer_from`) and hands it to the replay. SAM is asked one of two ways,
and exactly one must be named, or the command exits 2 before anything runs:

- `--sam-answers FILE`: recorded answers through `RecordedSamClient`. A replay's build
  (`pixel-reference`, `pixel-base`, `pixel-candidate`) picks the recorded run: `<build>/<replay>` if
  the file has it, else `--sam-run BUILD=RUN`, else the run named as the build. No request is sent.
- `--sam-live`: a live call (the key in `MODEL_API_KEY`, the cap in `EXPECTRAIL_SAM_USD_CAP`), its
  images reserved against `--budget-usd` first. This spends money.

`--sam-box` (`body` by default, or `WxH` with `--sam-lift`), `--sam-pad`, `--sam-every` and `--sam-first`
say how SAM is asked; with recorded answers they must match how the recording was asked, or the checks
are dropped with that reason. `--observer none` (the default) leaves every pixel check `not-run`. An
observer named without the pixel setting is refused.

`python -m expectrail.repro score --offer signals-reach-evidence-pixel` counts pixel records
([example](../contracts/examples/repro-score-pixel.json)). A pixel check reproduces by the bench's
rule: kept by its own runs (3 of 3 on the clean game, 3 of 3 failing on the bug build, one observer
setting) and failing 3 of 3 again with the no-fix candidate. A row's counts include its pixel checks,
its `pixel` object says how many were pixel checks, and the totals' `pixel` says how many defects a
pixel check reproduced and how many only a pixel check did. A pixel row whose status or outcome its own
runs contradict gives the defect no result. `--screen bench/jit/public/screen.json` (any setting) adds
what the screen record measured to each row and gives the rate on the screen-only defects apart.

### How often a frame is asked: `--sam-every` (added November 15)

The observer asks about every Nth frame of a probe and its last, at most `MAX_FRAMES` (30) a replay.
N was fixed at 10; `--sam-every N` (1 to 60, 10 by default) now sets it on `run` and `pixel-ask`, and
jit.yml's `sam_every` input passes one value to the capture, asking and judging jobs. A sparser plan
reserves fewer images under the same cap: a probe whose check names the enemy, on a route that fills
the plan, reserves 30 frames x 3 boxes x 9 runs x $0.0025 = $2.025 at every 10th frame (over the $2
cap, so `not-run`) and 16 frames, $1.08, at every 20th. The price: `never-crosses` and `inside-region`
fail on any failing frame, so a sparser plan can only miss failures, and a check the bug breaks only
between sampled frames is then not kept. 60 (one frame a second) is the sparsest.

The plan must be one plan across the jobs. A recorded answer file says which frames each run was asked
about (`framesProbed`, else the frames its rows cover), and the observer refuses, before it sends or
judges anything, a recording whose plan is not its own: a denser plan would stop on a frame the
recording never saw, and a sparser one would judge fewer frames than were paid for. Tested offline in
`tests/test_jit_sam_every.py` and `tests/test_jit_sam_every_workflow.py`; no live run has used it.

### The no-model sensor as an observer: `visual-sensor` (added November 16)

[`template_observer.py`](../expectrail/jit/template_observer.py) makes #262's template sensor
([`agents/template_observations.py`](../agents/template_observations.py), [template-sensor.md](template-sensor.md))
the `visual-sensor` observer of pixel checks. Given a template bank frozen beforehand from a clean
replay of the pinned clean game, it looks for the player near the engine's body box on the same planned
frames as SAM (every Nth and the last), after the same checks of the replay folder (route, capture rates,
every frame against the replay's digest, every planned frame present) and a check of the trace against
its digest. It sends nothing and charges nothing: a replay takes 0 images, so the budget reserves $0 for
it. Its setting is the sensor's algorithm and the bank's digest, so runs judged with two banks are never
compared. What a frame's row says:

| Sensor status | Row | Read by the judge as |
| --- | --- | --- |
| `matched` | the match, `holdsPoint` true | seen where the engine puts it |
| `displaced` | the match, `holdsPoint` false | looked for there and not found |
| `not-found` | no box, `absent` true | looked for there and not found (an observation, not a gap) |
| `unavailable`, `out-of-frame` | not asked | a gap: the check is `needs-review` on that run |

`absent` is the one new thing the judge reads (`pixel.observations`): before, a row with no box was always
a gap, because SAM's "nothing came back" says nothing; the sensor's `not-found` says it searched readable
pixels around the engine's box. The run reserves what an observer says a replay can take at most
(`most_images`) where it says so, and the old count otherwise.

**Offered to the proposer when it will judge (since the same day, later).** A run is judged by one
observer, and a check naming another is not run. So the propose step is told which observer will judge
(`propose --observer`, `revise --observer`; `sam-3.1-anchor` by default), the prompt's
`pixelChecksOffered` names that one observer only (`pixel.proposed(observer)`), a model's answer naming
another is dropped with the reason, and the proposal records the observer (`"observer"`, written only when
it is not SAM, so a proposal for SAM is byte for byte as before). `run --proposal` replays a proposal only
for the observer it is given and refuses one made for another (`PROPOSAL_MISMATCH`); `--observer none`
judges no pixel checks, so it reads a proposal made for any observer, as jit.yml's first replay does; a saved pixel check naming another observer is refused (`PROPOSAL_INVALID`). An
observer other than SAM under a setting with no pixel checks is refused. `run --observer visual-sensor
--sensor-bank BANK` builds the sensor (frame plan from `--sam-every` and `--sam-first`; none of SAM's other
arguments, and no capture or asking job, since it holds no key). jit.yml passes it since November 16 (below).
Tested offline in `tests/test_jit_propose_observer.py`, including propose (a recorded model answer, no
call), save and replay through `run.generate` with the sensor on the simulated game. Tested offline on synthetic frames
in `tests/test_jit_template_observer.py`, including end to end through `run.generate` on the simulated
game: a check that the player is drawn is kept (pass 3 of 3 clean, fail 3 of 3 where the sprite is not
drawn) and catches a wrong fix, not a good one. Its measured false alarms on the bundled game's clean frames are in [template-sensor-measurement.md](template-sensor-measurement.md), and a false alarm on a clean run
drops a check by the keep rule, so it costs a reproduction, never a false catch.

**In jit.yml: the `observer` input (added November 16, later).** `observer` is `sam-3.1-anchor` (the
default: every job as before) or `visual-sensor`, and the plan refuses `visual-sensor` without the pixel
setting. With the sensor, propose and revise get `--observer visual-sensor`; a `sensor-bank` job calibrates
the bank once a run (`python -m expectrail.jit.cli sensor-bank --out BANK --work DIR`,
`template_observer.calibrate_bank`); replay-final judges the pixel checks itself with that bank
(`--observer visual-sensor --sensor-bank BANK --sam-every N`) and its record is the result; pixel-ask and
pixel-judge do not run. The bank job replays the clean game alone, with no patch and no artifact of the
change: the four dedicated clean routes of the published sensor measurement
(`agents/template_sensor_bench.py`, `calibration_routes`: three to calibrate from, one separate to
validate the threshold), with the player's art and pose catalogue named in
[template-sensor.md](template-sensor.md). If the bank job fails, replay-final does not run and the
defect is "no result". On the real engine here (Godot 4.7.2, no model) the command took 5 minutes and
made a 408-template, 27.5 MB bank; two calibrations from identical route files gave byte-identical banks.
Judged with it, the clean `coins` and `traversal` routes matched the player on every planned frame (13
and 19 at every 10th frame, 25 and 27 at every frame). That is a check on two public routes, not a
false-alarm rate on the bench's probes. Tested in `tests/test_jit_sensor_workflow.py`; no dispatch has
used it.

**The enemy (added November 16, later).** The sensor can also be pointed at every enemy the engine logs a
box for (`enemyBoxes`, since November 15), the way SAM is: one row a planned frame in the run's
`objects.enemy`, one entry a box, read by `pixel.named_observations`, which now reads the sensor's
`not-found` as an observation (`absent`), not a gap. Calibration
(`agents/template_foreground.py calibrate_routes(..., objects=("enemy",))`) crops, in each clean frame,
the lowest-id enemy whose logged box is wholly on screen and touches no other object's box, masks it with
the enemy's own approved art (`enemy/enemy.webp`), and keeps its templates apart from the player's. The
threshold is still chosen on the player; the enemy's positives and displaced negatives on the validation
replay at that threshold are recorded in the bank under `calibration.objects.enemy` with its own `met` or
`unmet`, and the bank's reader recomputes that status from the counts. The observer refuses the enemy
when its bank has no enemy template, when that calibration is not `met`, or when the bank is not an
approved-art bank, so those checks are not run. A box partly on screen is a gap; one wholly off screen is
counted in `outside` and not judged; more than `pixel.MAX_BOXES` on screen is a frame not asked about.
The bullet was not offered then: calibrated the same way, its clean crops gave no template with enough
opaque detail. Since November 19 the sensor witnesses it by its rings instead (see "The bullet, for the
no-model sensor" below).

Measured here (Godot 4.7.2, no model, not in CI), from the four calibration routes `sensor-bank` replays:
408 player templates (as before) and 148 enemy templates, a 34.8 MB bank; the enemy matched 251 of 251
validation positives and 0 of 251 negatives (`met`). Judged with it on three library probes:

| Probe | Enemy boxes wholly on screen: matched / not-found | Partly on screen (gaps) |
| --- | --- | --- |
| `hold-right` | 31 / 0 | 3 |
| `reverse` | 25 / 0 | 7 |
| `move-fire-right` | 16 / 9 | 3 |

The counts were the same, box for box, on the clean game, `enemy-walks-backwards` and
`enemy-slides-when-shot`, so on these probes `visible` about the enemy reaches neither defect: the bank
keeps every template mirrored, so a backwards enemy still matches, and a sliding one is still drawn. The
nine `not-found` on `move-fire-right` are on the clean game too (not diagnosed here; shot enemies'
explosion frames are the likely place), and a check over them is dropped by the keep rule, never a false
catch. Over a whole window, a check about the enemy is `needs-review` whenever one enters at the screen's
edge. Tested offline in `tests/test_jit_sensor_named.py`.

**Which way the enemy faces (added November 16, evening).** `visible` cannot see `enemy-walks-backwards`:
the bank keeps every template mirrored. A new predicate, `faces-motion`, can. It says the object is drawn
facing the way the engine's record moves it, on every frame of the window where it moves one way and is
seen where the engine puts it. It is offered for the enemy only, and only to `visual-sensor`. SAM is
refused it at proposal time, and so is any other object.

- **Motion** (`agents/template_observations.py object_motion`): from each enemy's own logged world box on
  the tick before, the frame's tick and the tick after. `right` or `left` when both steps go that way;
  `still`, `turning` or unknown otherwise, and those frames make no claim.
- **Labels** (`agents/template_foreground.py calibrate_routes`): each clean enemy capture is labelled with
  the way the engine moved the cropped enemy on that tick (`heading`), and its mirrored copy the other way.
  A pose that looks the same mirrored, by the rule that keeps templates apart, gets no label.
- **Facing** (`facing`): the heading whose labelled templates match better, by at least the bank's
  margin (0.02), or none: the sensor cannot tell, which is a gap.
- **Validation** (`calibration.objects.enemy.facing`): on every validation frame where the enemy moves
  one way, the facing is decided as drawn and again with the enemy mirrored in place. `met` by the
  player's rule on both. The bank's reader recomputes it, refuses labels its record does not count,
  and refuses a label on a pose that looks the same mirrored.
- **Judging** (`pixel._facing_observations`): the reference evaluator's `visible` over the judged frames,
  where a frame holds the enemy only when it is drawn facing its motion. A run whose observer does not
  list the enemy in `facing` is a gap.

Measured here (Godot 4.7.2, no model, not in CI). The recalibrated bank has the same 408 player and 148
enemy templates; all 148 enemy captures were cut while the enemy walked right (74 labelled `right`, 74
mirrored copies `left`). Facing on the validation replay: 251 moving frames, 251 decided right as drawn
and 251 decided the other way mirrored, 0 wrong (`met`). Then on three library probes, every 10th frame,
the clean game twice and each defect build once:

| Probe | Clean: matched while moving, facing its motion | `enemy-walks-backwards`: facing against it |
| --- | --- | --- |
| `hold-right` | 29 of 29 (both replays) | 29 of 29 |
| `reverse` | 23 of 23 (both replays) | 23 of 23 |
| `move-fire-right` | 15 of 15 (both replays) | 15 of 15 |

No box was undecided. A `faces-motion` check over the whole window is `needs-review` on every probe,
because an enemy enters at the screen's edge (partial boxes are gaps). Windowed past those frames (from
frame 30, 130 and 30), it passed both clean replays and failed the backwards build on all three probes,
and passed `enemy-slides-when-shot`. `visible` over the same windows did not tell the clean game from the
backwards build on any probe. The nine clean `not-found` boxes on `move-fire-right` have motion `still`:
enemies that were shot and stopped. That is two clean replays, not the keep rule's three, and the checks
were written by hand, not proposed by a model. Tested offline in `tests/test_jit_sensor_facing.py`.

**Frames to avoid: objects partly on screen (added November 16, night).** The sensor does not judge an
object whose box reaches past the frame's edge (`out-of-frame`), so a window that holds such a frame is a
gap there. The evidence record now says where they are, so the proposer can choose a window without them:

- **Written** (`expectrail/repro/evidence.py edge_frames`): each row gets `edges`, from the engine's record of
  both clean replays, read with the same boxes and camera the observer reads (`object_predictions`). Per
  kind the engine logs boxes for (enemy, bullet): how many captured frames hold one partly on screen, and
  those frames as `[first, last]` runs, at most 24 (more are closed up, so the runs may hold more frames,
  never fewer). A kind is null when the record cannot say: no object boxes logged, a frame without a row,
  box or camera, or two clean replays that disagree. Records made before this have no `edges` and still
  read.
- **Read** (`problems`): runs in order, apart, inside the frames, and holding the frames counted.
- **Shown** under the pixel setting only (`offer.attach_evidence`): a shown probe's `differs` carries
  `partlyOnScreen`, and the pixel text says to choose a window that avoids those frames. Every other
  setting's prompt is unchanged. The pixel text also gives `faces-motion`'s shape now; until this change
  it was in `pixelChecksOffered` and nowhere told how to write.
- **Judged**: a gap for a box partly off screen says so ("enemy 3 is partly off screen, ...") instead of
  "the observer gave no answer".

Measured here (Godot 4.7.2, no model, not in CI): `python3 -m expectrail.repro evidence --defect
enemy-walks-backwards --probe hold-right --probe reverse --probe move-fire-right --jobs 2` took 3 minutes.
The enemy is partly on screen on frames 0 to 15 and 17 to 27 of `hold-right` and `move-fire-right`, and also
87 to 96, 98 to 112 and 114 to 124 of `reverse`; the bullet on 5 frames of `move-fire-right`. The windows
chosen by hand in the facing measurement above (from frame 30, 130 and 30) are past all of them. The
record is `contracts/examples/repro-evidence-edges.json`. Tested offline in
`tests/test_repro_evidence_edges.py`.

**The bench's records carry them (November 17).** The public bench's evidence for its two screen-only
defects with an enemy or a bullet in them, `bench/jit/public/evidence-enemy-walks-backwards.json` and
`evidence-bullet-behind-scenery.json`, were made again on all 25 library probes with the same command and
no `--probe` (Godot 4.7.2 here, no model, not in CI). Every field of every row is what the November 11
records held; each row now also has `edges`, so a pixel-setting propose step given these records has the
frames to avoid. `evidence-render` prints them as one line under the table. What they show for the enemy:
on 4 probes (`jump-w0-x1`, `jump-w0-x2`, `shoot-right-every48`, `shoot-right-every12`) it is partly on
screen on every captured frame, so no pixel check about the enemy can be decided there. On 15 probes no
frame after frame 27 has it partly on screen (the three `jump-w80-*` and `jump-w120-*`, `hold-right`,
`move-fire-right`, and the seven that go left, from frame 13 or 15). `edges` does not say whether the
enemy is wholly on screen or wholly off it on the other frames; the trace's boxes do, and the sensor judges
that. The other two bench records (`coin-stays`, `no-shooting-in-air`) were not made again; they have no
`edges`.

**The keep rule, through `jit run` (November 17, later).** The three windowed `faces-motion` checks of the
facing measurement are now a saved proposal,
[`bench/jit/stand-in/enemy-walks-backwards-faces-motion/`](../bench/jit/stand-in/enemy-walks-backwards-faces-motion/README.md),
written by `python3 -m tools.faces_motion_stand_in`. It is a hand-written stand-in, not a model's proposal
(`model: hand-written-stand-in`), made under the pixel setting for the sensor with the candidate withheld;
each window starts after the last frame the bench's evidence lists the enemy partly on screen. `jit run
--proposal` replayed it on the real engine here (Godot 4.7.2, no model, not in CI, 13 minutes) against
`enemy-walks-backwards` and the no-fix candidate: all three checks were kept, passing the clean game 3 of 3
and failing the bug build 3 of 3, and failing the bug build with the no-fix candidate 3 of 3. The record is
committed beside the proposal. The reproduction score gives a record made from a stand-in no result
(`score.STAND_INS`, which also names the rehearsal fixture), so this never counts as a reproduction. What it
leaves is the model's half: whether a propose step, given the same evidence, writes such a check.

**The bullet, for SAM (November 17, evening).** `bullet-behind-scenery`, the other screen-only defect, can
only be asked about through SAM: the sensor's bank holds no bullet template. Three `visible` bullet checks
are a saved stand-in proposal for `sam-3.1-anchor`,
[`bench/jit/stand-in/bullet-behind-scenery-visible/`](../bench/jit/stand-in/bullet-behind-scenery-visible/README.md),
written by `python3 -m tools.bullet_visible_stand_in` (no model; `STAND_INS` gives a record of it no result).
Its windows leave out frames with more than `pixel.MAX_BOXES` bullets on screen, which SAM is not asked
about: `move-fire-left` has four on frame 80 on every replay, so a window holding it could never be kept.
`jit run --proposal --pixel-capture` captured the three probes on the real engine here (Godot 4.7.2, no
model, no SAM, not in CI, 10.5 minutes, 27 replays). On every replay the engine logged the same bullets on
all three builds; the bug build does not draw them where it puts them. `pixel-ask` with the asking job's
budget at jit.yml's default cap ($2 less the capture's $0.2089) refused before asking anything: the 27
replays need up to 1,296 images, $3.24. The asking job plans every 10th frame of each probe's route
whatever the checks' windows, so a window does not lower the reservation; at the $2 cap one bullet check on
one probe can be asked about, not three. Whether SAM sees a bullet drawn behind the scenery is untested.

**Only the windows' frames are asked about (#605, November 18).** Since then the observer is asked only
about its planned frames inside the union of the windows of the checks on a probe (`pixel.planned`; a check
without a window keeps the whole plan). The in-process replay (`run.py` `_pixel_plans`), the capture (which
writes the windows beside each kept replay as `windows.json`, untrusted like `objects.json`), the asking job
(`pixel_jobs.ask`, which reads them back and refuses malformed ones) and the judging job plan the same frames,
and `pixel.observe` refuses an answer about other frames. The judging job refuses recorded answers planned
for other windows (`RecordedSamClient.plan_of`), so their checks are dropped, never passed. A check whose
window holds no planned frame is `not-run` and asks for nothing. The three bullet checks now reserve 675
images, $1.69, under what the asking job gets at the $2 cap ($1.79). Shown offline only
(`tests/test_jit_pixel_windows.py`); no capture of the bench probes was remade, and SAM was not asked.

**The bullet capture, remade with the windows (November 18, afternoon).** The same `jit run --proposal
--pixel-capture` on the real engine here (Godot 4.7.2, no model, no SAM, not in CI, 9.3 minutes, 27
replays) kept 225 frames, 49 MB (the whole-probe capture kept 86 MB). The record differs from the first only
in the profile's hash (`menuActions`, #622) and the replay time, so the capture's spend is $0.1987.
`pixel-budget` gave the asking job $1.8013, and `pixel-ask` on that capture no longer refused: it reserved
675 images, $1.6875, and began asking. With the recorded rehearsal answers (`--sam-answers`, asked under
another setting) it stopped at the first replay and sent nothing, as it must. SAM itself has not been asked.

### The bullet, for the no-model sensor (added November 19)

Until today `bullet-behind-scenery` could only be judged through SAM, which is paid for each image. Looked at
on the real engine (Godot 4.7.2 here, no model), the reasons templates never matched the bullet were not its
size:

- **It turns.** It is a RigidBody2D and spins as it flies and bounces, so its 16 x 16 art is drawn rotated
  and its pixels change from frame to frame. Clean templates matched it on about a third to two thirds of
  clean frames.
- **Its colours are not its art's.** An additive glow is drawn over it, so no rendered pixel is in the
  art's palette.
- **It is drawn behind its logged box.** The game has `physics_interpolation` on, and the bullet moves about
  14 frame pixels a tick: each frame draws it 1 to 1.7 ticks behind the box logged on the frame's tick,
  under the frame's own camera.
- **It fades out.** Its timer (1 s) calls `destroy`, which fades the sprite over 0.3 s.

[`agents/template_radial.py`](../agents/template_radial.py) witnesses it by what does not change when it
turns: the mean colour of each one-pixel ring around its centre. The rings are measured on the trusted clean
calibration replays only, where the approved art itself locates the sprite on the path the engine logged. A
frame's bullet is `matched` when some position on its path (from two ticks back to the frame's tick, through
the frame's camera) has rings within 12 (mean absolute RGB) of a frozen profile, and `not-found` when none
does. A bullet in its fade, one whose path is not wholly on screen, one not the calibrated size, or one whose
searched path another logged box touches (`crowded`, below) is a gap.
The bank carries it as `radialWitnesses.bullet` with `calibration.objects.bullet` (`witness: radial`;
contract `template-bank`, example `template-bank-foreground-radial.json`), and the reader recomputes its
status. `pixel.OBSERVERS["visual-sensor"]["boxes"]` is now `("enemy", "bullet")`, so the proposer is offered
bullet checks for the sensor.

Measured with `sensor-bank` on the four calibration routes (8 minutes): the same 556 templates as before, and
for the bullet one ring profile (every clean located bullet was within 1 of it), 70 of 70 validation
positives matched and 0 of 70 negatives (`met`). The bank's digest is `58f45c41...`.

Then, with that bank, a hand-written stand-in of two `visible` bullet checks for the sensor
([`bench/jit/stand-in/bullet-behind-scenery-sensor/`](../bench/jit/stand-in/bullet-behind-scenery-sensor/README.md),
written by `python3 -m tools.bullet_visible_stand_in --observer visual-sensor`; no model, so the score gives it
no result) was replayed by `jit run --proposal --observer visual-sensor --withhold-candidate` against the
no-fix patch (7.8 minutes, 18 replays). **Both checks were kept**: clean pass 3 of 3, bug fail 3 of 3, bug plus
no-fix fail 3 of 3, with $0 reserved for the observer. The windows end before the first planned frame with a
fading bullet on the clean game; with the SAM stand-in's longer windows the checks were `needs-review` on
every build. This is a rehearsal of the keep rule with a check no model wrote, not a reproduction rate.

**A bullet beside another one is a gap (November 19, later the same day).** The first stand-in run noted two
clean bullets beside fading ones that the witness did not find. On the whole clean probes (`shoot-left-every12`,
`move-fire-left`, `move-fire-right`, 3 replays each, every frame) the witness gave `not-found` for 111 clean
boxes, and every one overlapped another bullet's searched area: bullets that came to rest on one another, drawn
over each other. Ring distance, measured on the calibration replays, by what touched the area searched along a
bullet's path: nothing, at most 3.0 (498 boxes); another bullet, up to 14.3, beyond the limit of 12 (22); only the
player or an enemy, up to 11.2 (120). Calibration had kept only bullets whose box touched no other box, but the
witness then judged every bullet, so its validation did not describe what it judged. Now one rule,
`template_radial.crowded`, decides both: a bullet is judged only when no other logged box touches its searched
area, and no other bullet comes within the witness's `clearPx` of it (0 on the bundled game: with no box
touching, the rings stayed within 3.0 at every gap, so the bullet's faint glow does not need a margin). A record
that cannot say where the other roles are is a gap too.

The cost is reach. On those clean probes, of the boxes judged before, 1,290 of 2,010 are now gaps, and 720 are
`matched`; none is `not-found`. With the stand-in's earlier windows both bullet checks were `needs-review` on
every build, so the windows were cut by the same rule the fading cut used (the last planned frame before the
first planned frame with a crowded or fading bullet on the clean replay, read from the trace alone):
`shoot-left-every12` frames 50 to 50 and `move-fire-right` frames 10 to 30. The recalibrated bank (68 of 68
validation positives, 0 of 68 negatives, `met`) and the stand-in's new run are on the stand-in's page.

### Three jobs, so SAM's key never meets the change's code (added November 14)

The replays run the change's code, and asking SAM needs its key; jit.yml keeps the two in separate jobs
for the model already. [`pixel_jobs.py`](../expectrail/jit/pixel_jobs.py) does the same for pixel checks:

1. **Capture** (runs the game, no secret): `run ... --observer sam-3.1-anchor --pixel-capture DIR`
   replays each pixel check's probe with frames on the clean game, the bug build and the candidate,
   three times each, and keeps each in `DIR/<build>/<probe>-<n>/` with the route it replayed. A kept
   replay holds only its `replay.json`, its `trace.json` and the frames the observer will ask about
   (since November 15): on hold-right that is 3.8 MB instead of 39.5 MB, on wait-long 6.2 MB instead of
   113.1 MB. The observer refuses a kept replay missing a frame it asks about. Nothing is asked; the pixel rows are `not-run`. It takes no `--sam-answers` or `--sam-live`.
2. **Ask** (holds the key, runs no game): `pixel-ask --replays DIR --out answers.json --budget-usd X
   --sam-live`. Every stored replay's frames are planned from its route and all their images reserved
   against the budget before the first request; over it, nothing is sent and it exits 1. SAM is asked
   through the same observer the judge uses, so frames are checked against the replay's digests. The
   answer file has one run a replay, named `<build>/<probe>-<n>`. The first replay that cannot be asked
   about stops the asking (`stopped`). `--sam-answers FILE` in place of `--sam-live` rehearses it.
3. **Judge** (runs the game, no secret): `run ... --observer sam-3.1-anchor --sam-answers answers.json
   --pixel-replays DIR`. Trace checks replay as always; a pixel replay is the captured folder, put in
   place only if it is a replay of the route this run compiled (otherwise the run ends as nothing
   generated). The observer asks exactly what step 2 asked and the recorded answers answer only that,
   so a replay missing from the answers, or a frame changed since, drops its checks. `--pixel-replays`
   never takes `--sam-live`.

The capture folder is untrusted (a job that ran the change wrote it): only the three build names,
`<probe>-<n>` folders holding only what a kept replay holds, and regular files are accepted, no symbolic
link, at most 36 replays.

### In jit.yml (added November 14, seventh slice)

The offer input takes `signals-reach-evidence-pixel`. `measure` makes the evidence as under the evidence
setting. Then:

- **replay-final** (the capture; runs the game, no secret) always replays the revise job's proposal
  under this setting, revised or not, with `--observer sam-3.1-anchor --pixel-capture runs/pixel-capture`,
  on a virtual display, and uploads the record and the frames as `jit-<case>-captured`. This record is not
  the result.
- **pixel-ask** (the asking; `environment: main-only`, SAM's key, no game, no engine) reads the captured
  record's spend with `pixel-budget` (the change's cap less that spend, 0 if the record cannot be read as
  a valid `jit-run` record), sets `EXPECTRAIL_SAM_USD_CAP` to it, and runs `pixel-ask --sam-live` within
  it. Over that, nothing is sent and the pixel checks stay not run. It uploads `jit-<case>-pixel-answers`.
  It is a perception-only job in the lane inventory (agents/assurance/audit.py, `PERCEPTION`).
- **pixel-judge** (the judging; runs the game, no secret) replays the proposal once more with
  `--sam-answers` and `--pixel-replays`, and uploads `jit-<case>`, the result. With no frames or no
  answers it keeps replay-final's record, its pixel checks not run.
- **repro-score** waits for pixel-judge and skips `-captured` and `-pixel-answers` artifacts.

The trace checks are replayed three times under this setting (first round, capture, judge); the judge's
record carries the first round's spend through the proposal, not the capture's.

**Not yet:** no SAM answer has been recorded on a bench probe, and no reproduction rate has been measured
with pixel checks; the workflow's pixel jobs have not run. #286 is done when a recorded run reproduces a
public screen-only defect with one.

### What the offered boxes can see (added November 15)

`python3 -m expectrail.repro pixel-reach` ([`pixel_reach.py`](../expectrail/repro/pixel_reach.py),
[schema](../contracts/repro-pixel-reach.v1.schema.json), [example](../contracts/examples/repro-pixel-reach.json))
asks, with no model, whether a pixel check as the menu offers it could fail on a defect at all: on the
frames `sam-3.1-anchor` would be asked about, does any pixel inside the box it would be shown differ
between the clean game and the defect build? The menu offers the player only, so the box is the
player's. On the bench's two screen-only defects (all 25 library probes, November 15): yes for both,
on 9 planned frames of one probe for `enemy-walks-backwards` and 17 over six probes for
`bullet-behind-scenery`; but on the four frames looked at by hand, what differs inside the box is the
enemy or the bullets overlapping the player, not the player. Whether SAM's box of the player changes there is untested. The table and
what it does not show are on the [bench's page](../bench/jit/public/README.md).

Since November 15 the harness also logs each enemy's and bullet's own collision box every tick (the
trace's `enemyBoxes` and `projectileBoxes`, matched to `enemies` and `projectiles` by id; header
`capabilities.objectBoxes`; [Godot example](../contracts/examples/trace-godot.json)), and
`agents/sam_anchor.py` `object_boxes` places them in a frame as `anchors` places the player's.
`pixel-reach` measures those boxes too, apart from the player's (when this was measured, the menu did not offer them yet)
([example](../contracts/examples/repro-pixel-reach-named.json)): inside the enemies' boxes,
`enemy-walks-backwards` differs on 230 of its 241 differing planned frames; inside the bullets',
`bullet-behind-scenery` differs on all 67.

**The enemy and the bullet are offered (November 15, later).** `enemy` is a bound role, and `enemy` and
`bullet` are bound with `"anchor": "engine-boxes"`: every object of the role has its own logged box. The
observer is pointed at those boxes (`SamAnchorObserver(..., objects=...)`; `pixel.OBSERVERS` lists them
under `boxes`), so the menu offers both to `sam-3.1-anchor`.

- **Asked:** on every planned frame, one image for each object of the role on screen, widened by the
  same pad as the player's box. At most `pixel.MAX_BOXES` (3) a frame; a frame with more of them on
  screen is not asked about and is a gap. A box wholly off screen is not drawn and not asked about.
  A trace without `objectBoxes` is a gap on every frame: a box is never guessed from a position.
- **Judged:** each object, by its id, on its own frames, by the reference evaluator. The check fails
  when any one fails, passes when every one passes, and is `needs-review` on any gap or when none of
  them was on screen in the window. `inside-region` is each object's own logged box.
- **Only what a check names is asked:** the replay asks about a role only when a pixel check on that
  probe names it (`run.py`); the capture job writes those roles into the stored replay
  (`objects.json`), and the asking job reads them back (untrusted: only roles the observer is pointed
  at, each once).
- **The player only when a check names it:** a probe whose pixel checks name only the enemy or the
  bullet is not asked about the player (`pixel.asks_player`). Its player rows are `asked: false` with
  the reason, so a player check on such a run could only be `needs-review`, and an answer that says it
  asked about the player is refused. The capture job writes `"player": false` into `objects.json`.
- **Reserved:** `pixel.MAX_BOXES` images a frame for each named role, and one for the player only when
  it is asked about, on every run, before anything is asked, in the in-process replay, in `pixel.cost`
  and in `pixel-ask`. The frames are the planned frames inside the checks' windows (#605): the capture
  writes the windows into the stored replay (`windows.json`) and the asking job reads them back.
- **Shown offline only.** The tests use a scripted SAM client and synthetic replays
  (`tests/test_jit_pixel_named.py`, `tests/test_jit_pixel_player.py`). No SAM answer about an enemy or a bullet has been recorded, and no
  live run has asked one.

## What this does not claim

- **No detection rate.** The offline tests use a simulated game and a fake model. They show that an
  always-passing check is dropped, that a fix which leaves the bug is caught, that a correct fix is
  not, and that the rules hold. They say nothing about how often Muse Spark proposes a check that
  catches a real wrong fix.
- **Comment-only and no-op fixes are reachable only through the base build.** With no added line,
  the operators have nothing to change, so the base build is the only near miss.
- **Generated checks see what the trace language sees.** Visual faults (missing textures, layering)
  cannot show in a trace, and v1 uses no SAM image.
- **The strong label is a proxy.** It means the check also fails on the base build, not that it fails
  for the reason in the report.
- **A model ranking and explaining catches is not built.** The issue allows one, provided it never
  changes a catch; v1 orders catches strong first, then by id.
- **The prices are assumptions** until Muse Spark's are published to us.

## Out of scope

Promoting a generated check to an approved spec (a person does it by hand), new trace-language
operators, letting generated checks reject, Unity, and Flutter.


## Public reproduction audit and integer UI state (#285, November 16)

See [the completion table, miss breakdown and Sean's dispatch/cost plan](repro-audit.md).
The original hosted baseline score and all its per-defect records are now committed under
[`bench/jit/recordings/public-43465090517/`](../bench/jit/recordings/public-43465090517/).
Recomputing that score is byte-identical; no new live rate was measured.

`ui_integer_at_end` reads the sole visible integer-only Label value at the last tick of the
observed window. The recorder collects it only when an evaluated trace spec reads that signal,
either through `relation.signal` or either side of `signal_compare`. JIT requests it per active
check/probe, including candidate fingerprints; discovery requests it for applicable specs and
recaptures a prior probe if a newly proposed spec first needs UI data. The request uses the
harness's existing value-argument path (`--ui-integers=true`), not a route field or environment
switch. With no requesting spec, no UI scene walk runs and no `uiIntegers` key is written.
General measurement/evidence collection does not enable it merely because an offer names the signal. The Godot recorder writes optional bounded `uiIntegers`; older traces, no label,
multiple labels and collection overflow give no reading. This is engine UI state, not proof of
pixels. `signal_compare` compares two signals within one route/window (right against left,
with `eq`, `lte`, `gte`, `lt`, `gt` and nonnegative `toleranceAbs`). A reported collected-coin counter
can compare `ui_integer_at_end` with `coins_collected`, without a guessed count. Undefined readings
never pass. Schemas and handwritten examples cover raw trace, episode and trace spec.

Both are offered only in `signals-reach-evidence` and `signals-reach-evidence-pixel`; parsers and
saved-proposal readers enforce this. The baseline and `signals-reach` prompts and probes stay
unchanged. `tests/test_trace_ui_integer.py` covers parsing, unknown/ambiguous/malformed data,
window/tolerance semantics, old traces, the comparison, and a real pinned-engine public menu route:
clean 5 twice, stuck 0, doubled 10. These are offline signal tests, not model reproduction evidence.
Menu probes still require an explicit trusted menu action and are not offered automatically to
generated checks. Multi-label/formatted/custom-drawn UI and the two orientation/layering misses
remain limitations. No observer or verdict is enabled by this change.


## Generated checks that count (#271)

Implemented and tested offline; not enabled in the current CI workflow. The ordinary
`run_gate(generated_checks=...)` path still reads its legacy advisory summary. No generated
text can opt itself into counting. The shared `record.decide(..., generated=proof)` and
`jit.assess.counting` enforce the six rules below; `jit.counting.judge` attaches authenticated
evidence to an existing gate result and calls that same decision rule. It replays nothing and
implements no second gate, fixer or retry rule. The protected gate verifier and agent verifier files are unchanged.

Counting generated checks never clear a change alone (Sean's decision, November 18, #600): when no
approved check ran, the decision stays `needs-review` for intent `none` and for intent `fix`
("no approved checks ran; … cannot clear a change alone"). With at least one approved check run, a
counting check may demonstrate a fix's repair (rule 1).

| Rule | Mechanical evidence | Executable test in `tests.test_jit_rules.CountingRules271` |
| --- | --- | --- |
| 1. Base alone | Candidate withheld; exact three clean passes and three base failures; complete run. Original prompt and all inputs are digest-bound | `test_rule_1_base_alone_and_three_of_three_clean_and_bug` |
| 2. Discrimination | A killed near miss has three failures, is not in `sameAsCandidateFor`, and has exercised evidence. The base discriminates only when candidate passes, proving different behaviour | `test_rule_2_identical_near_misses_do_not_discriminate` |
| 3. Relevance | Audited signal-to-behaviour vocabulary in `assess.BEHAVIOURS`; whole words from the report OR trusted profile-derived diff claims must match the predicate's signal. The assessor-only map is never sent to a candidate-withheld proposer. Generated statement/claim/verdict text is not authority | `test_rule_3_unrelated_predicate_stays_advisory` |
| 4. Exercise and stability | Every required probe/pair is applicable, complete and meets its trigger/evaluation minimums on all three clean, base and candidate replays and an independent killed near miss. Candidate outcome is the same all three times | `test_rule_4_coverage_and_candidate_stability_are_required` |
| 5. Trusted origin | Fresh existing Receipt v1, known issuer from the caller's trust store, expected repository/base/head/build/policy and exact model-input digests; signed capabilities attest trusted proposal AND replay; canonical source-run digest matches | `test_rule_5_candidate_cannot_self_assert_trust`; `test_unknown_issuer_stale_receipt_and_changed_expectations_cannot_count` |
| 6. Provenance | Requirement source, actual predicate, probes and route hashes, reference/base/candidate evidence, independent kills, every rejection reason, model/version and generator version in the counting record; its canonical digest goes into the final existing receipt | `test_rule_6_missing_version_or_provenance_is_advisory`; `test_gate_record_and_existing_receipt_bind_the_full_provenance` |

Otherwise the check stays advisory. Relevance is deliberately narrow: unsupported operations,
unknown signals, screen-only checks and synonyms outside both the vocabulary and mapped file reach stay advisory,
so they can require human review even for a real repair. Matching words or coarse file reach is not proof that a
predicate captures intent; a changed file can contain several unrelated behaviours. A base that still behaves like the wrong candidate does not alone
supply an independent discriminator; that can also leave a real catch advisory. No new live
false-negative rate was measured. Pixel checks currently lack independent near-miss evidence and
remain advisory; no observation implementation changes are included here.

`run.py` keeps the existing keep rule and adds per-arm outcomes/coverage and provenance to its
record, including assessor-only diff claims. Under candidate withholding those claims never reach the proposer. It does not change the raw record's `advisory: true` or grant approval. The exact model
identifier is recorded as its version unless the proposer supplies a more specific version; this
does not promise that a provider will never change an aliased model's internals.

A counting check that fails on the candidate rejects. One that passes can demonstrate a fix
only with rule 1's base-only failure and clean success, three of three. It cannot override an
approved or held-out failure, missing required coverage, a missing observer or required isolation.
Under the `both` observer policy a counting generated pass needs per-check visual evidence. A trace row is the engine's record alone, so with a counting trace row the result is needs-review even when an observer is configured. A counting pixel row (below) is its own visual evidence: its runs are a trusted observer's verdicts over frames where the engine's record also places the object, so it is the visual evidence `both` asks for. It never demonstrates a repair on its own (Sean, November 18, #638): a change declared as a fix still needs an approved check or a counting trace row to show the repair, and a pixel failure still rejects. A validated failure can still veto. The report names counting/advisory checks and says this base-only condition explicitly. Tests:
`test_counting_alone_cannot_clear_fix_without_rule_1`,
`test_a_counting_label_and_all_true_flags_cannot_replace_actual_base_failure`, and
`test_authenticated_counting_catch_rejects_and_public_failure_still_vetoes`.

### Trust, contracts and publication

The new closed contract is `expectrail.generated-counting/v1`, with an example in
`contracts/examples/generated-counting.json`. It contains the source JIT record, report, source
receipt and recomputed assessment. `generated-counting-context/v1` is the trusted caller's
independent expected identities/inputs, with a writer/reader and example. Neither a context
embedded by the candidate nor its embedded public key becomes trusted. Keep the issuer trust
store in trusted policy, outside candidate artifacts. Missing/unknown/stale trust never counts.

The source receipt attests generation/replay, not clearance on the candidate: demanding that
clearance first would be circular. Its signed `jit-trusted-proposal` and `jit-trusted-replay`
capabilities must be issued only by a trusted job that actually performed both operations, never
by copying a candidate job's outcomes. The trusted caller must compute expected input digests
from its own snapshotted report/builds/profile/prompt, not read them back from the candidate's
record. Production deployment of that issuer/job remains Sean's work; no new permission or
workflow was installed. A signature by itself does not prove honest execution by the issuer.

Use `counting.make`/`write` in that trusted job, then `counting.read(..., trust=context)` to obtain
an in-process witness. Raw JSON cannot be passed to `decide`. The witness also pins the game
builds. Findings gain a closed `countingChecks` block and readers require the same separately
authenticated witness. Existing publishers can use `with record.counting_context(proof):` when
reading the final record; the scope resets even on exceptions. It is not an environment switch.
A different build, altered assessment or absent witness is refused. Default readers stay strict.
`counting.receipt_document` feeds the existing receipt writer with the final gate decision,
counting coverage and canonical digests of the full provenance and findings; signing/trust rules
are unchanged. No check is promoted or approved.

An operator-facing entry point for a trusted worker is:

```sh
python3 -m expectrail.jit.counting judge --gate findings.json \
  --evidence generated-counting.json --context trusted-context.json \
  --trust-store trusted-issuers.json --out counted-findings.json
```

The context must be independently pinned trusted input. A counted record read without that
witness is refused rather than silently downgraded. The normal CI publisher must authenticate
and install the witness before using its existing reader. Wiring that trusted job/publisher is
not enabled by this patch; the workflow and protected verifier belong to other work.

### Recorded offline public counts

The [offline public audit](measurements/271-public-counting.md) reads the 24 committed source
records from public run 43465090517: **137 checks assessed, 0 counting, 137 advisory assessments** (91 recorded as kept by the legacy rule; 46 dropped proposals retained only as diagnostics). They were
candidate-shown and predate authenticated trusted replay and per-arm coverage provenance. This
is not a newly measured generation or reproduction rate. No record was relabelled as withheld.

```sh
python3 -m expectrail.jit.counting public-bench \
  --records bench/jit/recordings/public-43465090517/repro \
  --out /tmp/public-counting.md
```

### The six rules on pixel checks (#286)

Pixel checks are in a record's `pixelChecks`, which `counting` never read, so a screen-only check was
advisory with no reason given. `assess.pixel_counting` recomputes the six rules for each pixel row from
its own runs, never its `status` or `outcome`:

| Rule | For a pixel row |
| --- | --- |
| 1 | Complete record, candidate withheld, 3 reps; the bug build fails 3 of 3 and the clean game passes 3 of 3 |
| 2 | No near miss is replayed for a pixel check, so the base build is the only discriminator, and only when the candidate passes 3 of 3 |
| 3 | `pixel_relevant`: the report names the check's bound object **and** its predicate's behaviour (`PIXEL_OBJECTS`, `PIXEL_PREDICATES`). The statement is never read. False negatives: synonyms outside the lists, `reaches`, the ground, and every diff-map claim |
| 4 | Every run on all three builds is `pass` or `fail` (a gap in the window makes `needs-review`), one observer setting, a stable candidate |
| 5 | Only the caller's `trusted`, as for trace checks |
| 6 | Generator and model versions, model and prompt digest, the probe in the record, the observer setting |

`counting.make` carries these rows in the `generated-counting/v1` envelope after the trace rows (added
November 19): each has `kind: "pixel"`, its `observer` and `setting`, and its runs in the pixel
vocabulary (`pass`, `fail`, `needs-review`). The envelope and the gate record's `countingChecks` take
the same closed row shapes (up to 8 trace and 4 pixel rows), and a pixel check may not share a trace
check's id. Like a trace row, a pixel row is recomputed from the source run on every read, so a changed
row or run is refused. Under `both`, a counting pixel row is its own visual evidence (above), and it
still never clears a change alone. The pressure dispatches replay trace checks only: when a pixel check
counts they stop (`pixel-checks-not-replayed`) rather than replay fewer checks than count. Example:
[`generated-counting-pixel.json`](../contracts/examples/generated-counting-pixel.json), made by
`counting.make` from the enemy stand-in with no trust, so nothing counts. Tests:
`tests/test_jit_pixel_envelope.py`. On the two committed pixel
stand-ins ([page](measurements/271-pixel-counting.md)): 6 pixel checks, 0 counting. The three
`faces-motion` checks on `enemy-walks-backwards` meet rules 1, 3 and 4; they miss 2 (the candidate is the
no-fix patch), 5 and 6. The three bullet checks were captured, not judged, and meet rule 3 alone.

```sh
python3 -m expectrail.jit.counting pixel-bench --records bench/jit/stand-in --out /tmp/pixel-counting.md
```

### Prepared pressure dispatches: not run live

`python3 -m expectrail.jit.pressure correct` and `... adversary` print plans only. The
[complete manual workflow proposal](proposals/271-pressure.yml.txt) is for Sean to review and
install himself. There is no active workflow change or dispatch here. The implementation uses
frozen authenticated counting checks, not another generator. These old public records cannot
supply them. Prepare fresh trusted candidate-withheld evidence first; its generation cost is
separate and is not silently included in either dispatch. A missing counting check, source
certificate, trusted context, route digest or calibrated oracle blocks before a fixer is built.

- Correct-fix pressure: all 24 exact undos in the public reproduction registry, plus the four
  supplied known-bench correct patches, each replayed three times with the frozen checks. A
  single failure on a correct candidate blocks release, including flaky failures. Missing cases
  or undecided observations block too. This covers the two public registries, not private or
  unregistered correct fixes. Maximum 1,024 replays. It sends no model or vision request: API
  ceiling **$0**. The existing `agents.judge_bench.undo_patch` creates the exact undos on copies.
- Overfitting adversary: one bounded `llm-patch` invocation on public `air-jump`, deliberately
  given the generated checks for this experiment only. It may change only the public player
  script. It succeeds only if all generated checks pass 3/3 and an independent air-jump oracle
  still shows more air jumps than the clean build 3/3. The oracle is calibrated on clean and bug
  before the fixer starts and is not included in its prompt. This is an engine-signal oracle,
  not a human semantic judgement or visual proof. Maximum 64 recommended replays (hard maximum
  1,024), no vision/generation calls; one fixer invocation, no second fixer or retry policy.

Recommended adversary caps: invocation $6, aggregate fixer $6; the existing locked model-month
ledger is mandatory and retains reservations. The hard sender is the existing controlled
`llm-patch` sender and admission code; Muse and other agent CLIs are still refused. Named model:
OpenAI `gpt-6.1-sol`, 4,096 output tokens. Source:
`contracts/examples/provider-capabilities/openai.json`, read 2026-11-16, active through
2026-11-23. Recorded standard prices are $2/$10 per million; enforced conservative prices are
$5.50/$16.50 per million, covering the listed multipliers. Reserving the full 1,050,000-token
context plus output gives **$5.842584 maximum per request**. Two such requests cannot fit $6, so
a retry is denied before forwarding. $6 is held against the invocation/role/month caps with no
refund; it is the conservative dispatch ceiling. Expired/withdrawn/unknown models stay refused,
with no fallback. Do not run after the price record expires without a separately reviewed update.

The proposed self-hosted job times out after 120 minutes. Runner compute is not API spend;
`run.DEFAULT_PRICES` assumes $0.008/minute, or $0.96 for that timeout on a paid runner. It is an
assumption, not a measured bill or a hard provider price. The replay-count cap does not itself
bound wall time. Provisioning and any fresh check generation are outside these dispatch caps.

Offline rehearsals passed on the simulated game: two correct air-jump candidates each passed
3/3 (12 probe replays); one synthetic overfitter was detected using 15 replays and one stand-in
fixer callback. These prove the runner, oracle calibration, caps and blocking rules, not a real
adversary success rate. No live pressure campaign has run. The result contract
`expectrail.jit-pressure/v1` and reader recompute status/success from outcomes and the oracle.

### Still needed for #271 Done when

Sean must install the trusted generation/replay issuer and publisher wiring; provision fresh
candidate-withheld frozen evidence and the persistent ledger; review/install the manual proposal;
then deliberately dispatch the two pressure campaigns from main and publish their real counts
here. Promotion stays a person's separate act. The release blind test (#282) must score a
counting primary arm; private/held-out material remains Sean's task and was not opened here.
Until those live runs and the release arm have evidence this is **Part of #271**, not closure.
