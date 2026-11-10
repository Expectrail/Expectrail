# Generated checks: tests written for one change

Built November 10, 2026, for issue #204. **Nothing on this page is measured yet.** The code, the
record, the gate wiring and the offline tests are in place; every number the issue asks for is still
to be run, and the [measurement plan](#measurement-plan) says how.

For each change an agent proposes, Expectrail can now generate checks aimed at that change, keep only
the ones that are valid and deterministic, run them on the candidate, and report what they catch. It
is modelled on Meta's Just-in-Time tests (Meta Engineering, "Just-in-Time tests", October 29, 2026;
FSE 2026, arXiv [2601.22832](https://arxiv.org/abs/2601.22832)). It is aimed at the largest gap we
have measured: only checks people wrote can reject a change, they caught 10 of 77
generated single edits (0.9% weighted, [`bench/mutation/`](../bench/mutation/README.md)), and there
is no catch yet on a real agent fix that nobody anticipated.

**v1 is report-only.** A generated check never accepts or rejects a change. It is shown beside the
decision, like advisory discovery ([discovery.md](discovery.md)), until a person promotes it to an
approved spec by hand.

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
| CLI | [`cli.py`](../expectrail/jit/cli.py) | `run`, `measure`, `propose`, `revise`, `report`, `gate-summary`, `diff-games`. |
| CI | [`.github/workflows/jit.yml`](../.github/workflows/jit.yml) | Rehearsal on pull requests that touch this code; `live` by dispatch. |
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
and reads the pull request only as data: a `workflow_run` workflow, or a reviewed
`pull_request_target` exception such as `private-scan`. That is not built. Until it is, generated
checks are proposed by dispatching `jit.yml` from main (`live`).

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

None of this has run. Each row will link its CI run when it does.

| Measure | Baseline today | Target for v1 to be worth keeping | Result |
| --- | --- | --- | --- |
| Mutation bench Part 2 (generated bugs), weighted catch rate, approved checks plus generated checks | 0.9% (10 of 77) | Clearly above, with the per-class table | not run |
| Mutation bench Part 1 (wrong fixes), catch rate | 31 of 39 | No loss; extra catches among the 8 missed | not run |
| False alarms on the clean game | 0 | 0 | not run |
| False catches on correct fixes (the judge benchmark's 8 correct fixes, 3 runs each; the 10 live demo-path fixes) | none measured | 0 strong; weak reported | not run |
| A natural catch: a generated check fails on a real Muse Code fix the approved checks accepted, confirmed wrong by a person | 0 | 1 or more, or an honest "none" | not run |
| Determinism: the same change, 10 reruns | none measured | The same catches every time | offline only (simulated game) |
| Spend per change | none measured | $2 or less, median reported | not run |

The stress tests, in the order we intend to run them:

0. **The known-bugs bench, live** ([`bench.py`](../expectrail/jit/bench.py),
   [`bench/jit/known/`](../bench/jit/known/), `jit-bench.yml`). Rehearsals replay a committed stand-in, so
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
2. **Blind set 3.** Frozen in the private held-out repository (digest `a5ffad12…`, game commit
   `f864af5d…`). One run, at one commit that freezes the verifier, specs, harness, generator and game,
   in two arms (approved checks only; plus generated checks), after recomputing the digest. The
   implementers never read `fresh-3/`. *Open point:* the issue describes the set as 8 defects and 8
   wrong fixes; the frozen set has 10 entries, 8 defects and 2 intentional changes. The run will be
   reported against the set as frozen, and the difference stated.
3. **Correct-fix pressure.** Every correct fix we have, three runs each. A strong catch on a correct
   fix is a bug in the filter and is looked at before anything else.
4. **Overfitting adversary.** A separate fixer instance gets the generated checks for one bug (only in
   this test) and is asked for a wrong fix that passes them. Not built yet.
5. **Prompt injection and outage.** Offline, in `tests/test_jit_rules.py` (rules 5 and 3). Done, on the
   simulated game.
6. **A second domain.** One pass on the web checkout page (`apps/checkout`). Not built yet: the diff
   map, near misses and replays here are Godot's.
7. **Flake.** 10 reruns of the same change, live.

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
