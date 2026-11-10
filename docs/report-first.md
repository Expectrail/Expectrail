# Report first, verify always

The decision followed the natural-catch trial on October 30, 2026, and was amended on October 31,
after the first Fix matrix run to measure it. The fixer starts with a plain bug report. Expectrail
checks every candidate and accepts it only when every check passes; after any failed attempt, the
fixer receives Expectrail's detailed evidence.

> **October 31 amendment.** The first claim behind this decision, that the fixer does not need
> our evidence, did not hold for the sinking bugs. In Fix matrix run 41223754703, report-only
> attempts on both sinking bugs timed out three times in a row, while the evidence fixed each on
> the first attempt. Because a timed-out attempt did not count as a failure, the loop never
> escalated on the bug where it mattered most. Now any failed attempt escalates: a rejection, a
> timeout, or an attempt that changes nothing. The evidence has also been rewritten below
> ([What the October 31 run changed](#what-the-october-31-run-changed)).

## The decision

1. **The first attempt gets the report.** Muse Code gets what a developer would get: the failing
   check's sentence in plain English (or, for a reported bug, the reporter's own words), six
   screenshots of the failing run spaced from its first frame to its last, the route and the run's
   log. No spec, no verdict, no evidence.
2. **Every candidate is verified, on every attempt.** The fixer never decides that it is done. A
   candidate is accepted only when every check passes, as before.
3. **After any failed attempt, the next one gets the evidence:** the repair request (the approved
   spec, the evaluator's verdict on the failing run, its first failing frame) and, after a
   rejection, the public checks that did not pass. An attempt fails when the verifier rejects it,
   or when it produces no fix (it times out or changes nothing). Until October 31, an empty or
   timed-out attempt stayed on the report.
4. **The fixer never learns about the held-out routes or the guards.** Not their names, not that
   one failed, not why. When only a held-out check rejected a candidate, the fixer learns that the
   attempt was rejected and nothing else.
5. **Inside the verifier, cheap checks reject first and SAM confirms.** See
   [Cost inside the verifier](#cost-inside-the-verifier) for what this changes and what it does not.
6. **A judge that cannot answer is not a rejection.** When SAM does not answer, the same candidate
   is judged again, then by Glimmer checked against the engine, then left for a person. The fixer is
   not asked for another fix ([fallbacks.md](fallbacks.md)).

Before this, the fixer got the evidence from the first attempt, and the verifier's full reasons
after a rejection.

## What the October 31 run changed

[Fix matrix run 41223754703](https://github.com/Expectrail/Expectrail/actions/runs/41223754703)
([`bench/fix-matrix/report-first/`](../bench/fix-matrix/report-first/README.md)) ran the 8 development
bugs under all three conditions, with SAM on and the private routes mounted:

| Condition | Fixed | Fixed on the first attempt | Not fixed |
| --- | --- | --- | --- |
| `expectrail`: the evidence from the first attempt | **8 of 8** | 8 | none |
| `escalate`: the report first, the evidence after a failed attempt (as it then stood) | 7 of 8 | 6 | sinking/v1: three timeouts |
| `screenshots`: the report on every attempt | 6 of 8 | 6 | sinking/v1 and sinking/v2: three timeouts each |

- **Every failure was a sinking bug, and every one was a timeout.** Muse Code ran out of time
  without changing a file it may edit. With the evidence (the spec, the verdict and the first
  failing frame), it fixed both sinking bugs on its first attempt. In a sinking bug the robot is
  drawn or collides a few pixels into the ground, which is easy to miss in a screenshot and easy
  to find with a verdict that names the frame and the boundary.
- **Escalation helped where it was allowed to run.** On sinking/v2 under `escalate`, the first
  attempt timed out and the second, still on the report, was rejected. The third attempt got the
  evidence and was accepted. On sinking/v1 every attempt timed out. A timeout did not count as a
  failure then, so the evidence never came. That is the rule this amendment changes.
- **Across every live run so far, both held-out fix-matrix runs included:** report-only first
  attempts fixed 57 of 63 cases (90%) and evidence-first ones 39 of 42 (93%). Every first-attempt
  miss under either briefing was a sinking bug. The evidence's three were each fixed on the second
  attempt; of the report's six, one was ever fixed, on the attempt that got the evidence. The
  difference is concentrated in one family. It is still a small sample, and Muse Code does not give the same
  answer twice.
- **The other decisions stand.** Every candidate is still verified. The judge results are
  unchanged. The demo loop under the new policy accepted 3 of 3 runs on the first attempt from the
  report ([run 41223748922](https://github.com/Expectrail/Expectrail/actions/runs/41223748922)).

**What would make us switch back to evidence first:** if the next matrix run with the amended rule
still loses cases that `expectrail` fixes, or takes much longer to fix them, the evidence should go
first, and the report becomes the fallback for fixers that cannot read our contracts.

## Why

### The fixer usually does not need our evidence (as of October 30)

This section is the evidence as it stood when we decided. The October 31 run below changes it.
Every live repair we had run, with and without Expectrail's evidence:

| Run | What Muse Code got first | Fixed | First attempt |
| --- | --- | --- | --- |
| Fix matrix, development bugs ([`bench/fix-matrix/`](../bench/fix-matrix/README.md)) | Screenshots and the expected behaviour in plain English | 8 of 8 | 8 of 8 |
| The same 8 bugs | Expectrail's evidence (spec, verdict, first failing frame) | 8 of 8 | 7 of 8 |
| Natural-catch trial, 4 reported bugs × 5 ([`bench/reported/trial.md`](../bench/reported/trial.md)) | The reporter's own words and screenshots | 20 of 20 | 20 of 20 |
| Demo loop, 10 live runs ([`bench/demo-loop/`](../bench/demo-loop/README.md)) | Expectrail's evidence | 10 of 10 | 10 of 10 |
| Demo loop on this policy, 3 live runs ([41223748922](https://github.com/Expectrail/Expectrail/actions/runs/41223748922), Oct 31; [a review](review/report-first-run-1/)) | A plain report | 3 of 3 | 3 of 3 |

That was 48 of 49 cases fixed on the first attempt, counting the October 31 demo runs. The one
that needed a second attempt had the evidence. On those bugs, the evidence did not help Muse fix
anything it could not fix from a report. The October 31 Fix matrix run found bugs where it did.

### The judge is what matters

The judge benchmark ([`bench/judge/`](../bench/judge/README.md)) gave the same 15 candidate fixes
to three judges, twice. Seven of them only look right: one draws the robot inside the ground,
another moves the floor's collision below its art, another hides the robot behind the scenery.

| Judge | Bad fixes accepted (of 7) | Good fixes accepted (of 8) |
| --- | --- | --- |
| Expectrail with SAM | **0** | 8 |
| Expectrail, position log only | 3 | 8 |
| Muse Code from before-and-after screenshots | 2 | 6 and 7 |

Fixing is mostly the part Muse Code does well; the sinking bugs are the exception
([above](#what-the-october-31-run-changed)). Judging is where a fix that only looks right gets
through, and only Expectrail with SAM let none through.

### Why not "let Muse fix it, and run Expectrail only if Muse cannot"

We considered running the verifier only when Muse could not fix the bug. That would remove the
gate. "Muse fixed it" can only come from Muse, and Muse believes in exactly the fixes that matter
most: the ones that only look right. Shown the screenshots, it accepted 2 of 7 of them. A fixer's
confidence in its own fix is no better evidence than that. Under that rule, a fix that draws the
robot inside the ground would never trigger "Muse cannot fix it", so it would ship. So the gate
stays on every candidate, and what moves is what the fixer is told.

## First live runs

- **Demo loop, October 31** ([run 41223748922](https://github.com/Expectrail/Expectrail/actions/runs/41223748922),
  [`bench/demo-loop/report-first/`](../bench/demo-loop/report-first/README.md)): **3 of 3 accepted, each on
  the first attempt from the report.** Every review against the failing base showed the repair, and SAM
  judged every run with nothing falling back. Each run used 157 SAM images, against 1,164 in the earlier
  demo runs; those ran before the clean game's SAM answers were shared across a run's jobs, so the
  drop is mostly that change, not this one.

## What this buys

- **A product that does not care who writes the fix.** The first attempt's briefing is a plain
  report anyone could act on. Muse Code, another coding agent or a person can write the fix;
  Expectrail decides whether it ships. On most bugs the numbers above agree. On the sinking bugs a
  fixer working from the report alone often ran out of time, which is why any failed attempt now
  brings the evidence.
- **Harder to fix to the test.** A fixer that never sees the spec's assertion, its threshold or a
  verdict on the first attempt cannot aim at them. Most fixes are accepted on that first attempt.
  The held-out routes and the guards are never mentioned at all, so a fix cannot be tuned to them
  on any attempt.
- **A narrower claim about the fixer.** We do not claim Expectrail's evidence makes Muse a better
  fixer in general: on every family but one it made no difference. On the sinking bugs it did. The
  claim we lead with is the one measured most: Expectrail is a better judge.
- **A cheap fallback, kept.** After any failed attempt (a rejection, a timeout, or no change), the
  fixer gets Expectrail's evidence on the failing base, and after a rejection also which public
  checks failed. That costs nothing until an attempt fails.
- **One setting to undo it.** `EXPECTRAIL_BRIEFING=evidence` restores the evidence from the first
  attempt.

## What we do not know yet

- **How much the evidence helps after a failed attempt.** One measured case so far: sinking/v2
  was fixed on its third attempt, the first with the evidence. The amended rule (a timeout also
  escalates) has not run live yet. The Fix matrix runs `escalate` by default, so the next run
  measures it.
- **Whether a report is enough.** It was not always, even for small, local changes: each sinking
  bug is a one-line fix. A bug that spans several files, or whose obvious fix is wrong, may need the
  evidence from the first attempt.
- **Overnight, the "report" is still Expectrail's own check.** When no person reported the bug,
  Expectrail's check found it, and the report is that check's sentence. The fixer still does not
  see the spec, the verdict or the evidence until a rejection.
- **The report costs one more replay.** The screenshots come from replaying the failing game on the
  route, about half a minute on a CI runner. The evidence briefing did not need it.

## Cost inside the verifier

The rule: **a cheap check should reject before a paid one runs, and SAM should be paid to confirm
an accept, not to find a reject the engine already found.** The opposite rule, SAM only when the
cheap checks fail, would be wrong: a fix that only looks right passes the cheap checks, and that is
exactly where SAM earns its cost.

What already follows the rule:

- **Private routes are skipped after a definite fail.** Once a candidate fails a public check, the
  held-out routes cannot change the decision, so they are not replayed
  (`EXPECTRAIL_HELDOUT_AFTER_FAIL=run` replays them).
- **The clean game is judged by SAM once per run.** Its answers are shared, encrypted, with every
  job (`sam_cache`).

What we did not change:

- **SAM still looks at the candidate's smoke replay before the engine verdict is known.** Reordering
  this would save about 150 SAM images, roughly $0.40, per rejected candidate (the held-out bench
  used 746 images over five routes). With 3 rejections (and 17 timeouts) in the 87 attempts of the four
  fix-matrix runs, that is not worth changing the verifier's order days before the deadline. If harder bugs make rejections common, it is the next
  change.

## What changed in the code

- [`agents/escalation.py`](../agents/escalation.py): the policy. It builds the report and the
  evidence briefings, and the public feedback after a rejection.
- [`agents/loop.py`](../agents/loop.py): the overnight loop replays the failing base for the
  report's screenshots. It briefs each attempt by the policy and records each attempt's stage
  (`report` or `evidence`).
- [`agents/matrix.py`](../agents/matrix.py) and
  [`.github/workflows/fix-matrix.yml`](../.github/workflows/fix-matrix.yml): the condition
  `escalate`, run by default beside `screenshots` and `expectrail`.
- [`agents/bench_collect.py`](../agents/bench_collect.py): reads `escalate` results.
- [`tests/test_escalation.py`](../tests/test_escalation.py) covers the policy and the loop. The
  loop test checks this order: report, an empty attempt, then the evidence, a rejection, the
  evidence again, accept, with every candidate verified. It also checks that a held-out failure never reaches the
  fixer.

The natural-catch trial (`agents/reported_trial.py`) is unchanged. By its protocol, the fixer gets
the report on every attempt and never the evidence.
