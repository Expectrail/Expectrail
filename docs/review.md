# Reviewing a fix against its failing base

The verifier checks whether a candidate passes Expectrail's checks. The review asks a different
question: **did the requested behavior fail before this patch and pass after it?** It
runs the repair request's public checks on the failing base (the seeded bug, without a fix) and on
the candidate (the same game with the patch), using the same code, route and observer. It compares
each claim before and after. A pass on the clean game does not show that the bug was
present before this patch; only the failing base can show that.

A review describes evidence for these checks on this route. It is not proof that the game is
correct, and no status authorizes a merge or a release.

## What a review can say

| Status | When | Exit |
| --- | --- | --- |
| `REPAIR DEMONSTRATED` | The verifier accepts, every required check passes after the change, every requested check could be compared and passes after, and at least one requested check went from FAIL to PASS. A live review also needs fresh replays and the private routes. | 0 |
| `REJECTED` | The verifier rejects, a required check fails after the change, or the patch edits paths the request does not allow. | 1 |
| `NO REPAIR DEMONSTRATED` | Everything passes after the change, but no requested check was failing before it. A check that passed before and after (`PRESERVED`) shows nothing was repaired; an optional check changing never counts. | 1 |
| `INCONCLUSIVE` | Something needed is missing: an arm did not finish, an observation is missing or needs review, the two arms were judged differently, or a live review lacks the private routes. | 2 |

Each check gets one comparison: `REPAIRED` (fail before, pass after), `PRESERVED` (pass, pass),
`REGRESSION` (pass, fail), `UNRESOLVED` (fail, fail) or `INCONCLUSIVE` (anything else, including a
missing or needs-review result on either side). A check the request names as failing is
*requested*; only requested checks can show a repair. The others are guards: they must pass after
the change.

The evidence label comes from what each arm recorded, never from the mode asked for:

| Label | Meaning |
| --- | --- |
| `FRESH LIVE` | Both arms replayed now by the harness, the clean game too, and the private routes judged (or not needed after a definite fail) |
| `SAMPLE` | Recorded observations (fixtures), no new replays |
| `MIXED OR INCOMPLETE` | Any arm missing, a fixture fallback, or the private routes unavailable |
| `RECORDED LIVE` | Reserved for an archived live record shown again |

Where the patch came from is recorded separately (`muse`, `fixture` or `developer`): a fixture
verified on fresh replays is still a fixture, never a model's repair.

## Running one

    # Live: replays both arms (needs Godot; the private routes for a repair to be claimed)
    python3 -m agents.review_change --request rr.json --candidate fix.patch --out runs/review

    # Reuse a verification already made for this exact patch and request (the loop does this)
    python3 -m agents.review_change --request rr.json --candidate fix.patch --out runs/review \
        --verification runs/verify/verification.json

    # Sample: on fixture observations, labelled SAMPLE
    python3 -m agents.review_change --request rr.json --candidate agents/fixtures/fix-collision-mask.patch \
        --out runs/review-sample --mode sample \
        --base-observations agents/fixtures/obs-fallthrough.json --observations agents/fixtures/obs-fixed.json

    # The record as a page that opens from disk
    python3 -m agents.review_html runs/review/change-evidence.json

In the overnight loop, `EXPECTRAIL_REVIEW=on` reviews each run's final fix after verification,
reusing that verification, and reports the review in its own morning-report section beside the
verifier's decision, which it never changes. The fix matrix's demo jobs review every run by default (the `review` input turns it off), since
3 of 3 live runs passed with it. The
`sam-probe` workflow's verify mode reviews any fixture patch with SAM on and the private routes, and
keeps the review (its record, the public route's two frames and its page) as the `sam-review`
artifact once the export scan, compared with the private set, finds nothing.

## What the record holds, and what it never holds

`change-evidence.json` follows a closed schema (`contracts/change-evidence.schema.json`; the
example is a real sample review). It names the request, the patch and the verification by
digest; each arm's provenance, replay digest and observer; one row per check; the stages; any
diagnostics with a stable code; the status, label and reasons; and the command to run it again.

- The private routes appear as counts only: no route names, paths or frames.
- A missing artifact has no digest (null), never an all-zero one.
- Frames are the first failing frame of the base and the same frame of the candidate, with their
  SHA256; the page shows a frame only while its file still matches, and says so when it does not.
- A review is never overwritten. A verification is reused only when it is bound to the same patch
  and request. The command never runs a fixer.
- A crash leaves a record with the failure classified (`expectrail/diagnostics.py`): a crash or a
  provider error is never recorded as a behavioral failure.

## Measured

| What | Result | Run |
| --- | --- | --- |
| Overnight demo loop as it ships (#122, #123): Muse Code fixes from a plain report, SAM on, private routes, review on | 3 of 3 accepted on the first attempt; every review `REPAIR DEMONSTRATED` on `FRESH LIVE` evidence; 7 to 12 minutes and 157 SAM images a run | [41223748922](https://github.com/Expectrail/Expectrail/actions/runs/41223748922); run 1's review, with its frames: [report-first-run-1](review/report-first-run-1/) |
| Overnight demo loop, live, review on: Muse Code fixes, SAM on, private routes | 3 of 3 accepted; every review `REPAIR DEMONSTRATED` on `FRESH LIVE` evidence; 6 to 9 minutes and 157 SAM images a run, the failing base's look included (the first 10 run demo, before the shared SAM cache, used 1,164 a run: [bench/demo-loop](../bench/demo-loop/README.md)) | [41105875960](https://github.com/Expectrail/Expectrail/actions/runs/41105875960); run 1's review, with its frames: [live-demo-run-1](review/live-demo-run-1/) |
| The correct fall-through fix, SAM on, private routes | `REPAIR DEMONSTRATED`: the ground and visibility checks FAIL to PASS, coins PASS to PASS | [41101872602](https://github.com/Expectrail/Expectrail/actions/runs/41101872602) |
| The fix that draws the robot inside the ground, SAM on, private routes | `REJECTED`: the fall stops (motion FAIL to PASS) but the requested ground check and visibility stay FAIL to FAIL | [41101881327](https://github.com/Expectrail/Expectrail/actions/runs/41101881327), and again in [41123758768](https://github.com/Expectrail/Expectrail/actions/runs/41123758768), whose review is kept with its frames: [sinking-fix](review/sinking-fix/) |
| Every pull request, real replays, SAM off, no private routes | The correct fix shows FAIL to PASS and is `INCONCLUSIVE` (no repair claimed without the private routes); the fix that moves the floor's collision below its art is `REJECTED` | `agents-harness-verify` in [ci.yml](../.github/workflows/ci.yml) |
| Main, real replays, SAM off, private routes | The correct fix is `REPAIR DEMONSTRATED` on `FRESH LIVE` evidence, and the record names no private route | `agents-harness-private` in [ci.yml](../.github/workflows/ci.yml) |
| A fallback night, live (the fourth drill, after #146): SAM made unavailable once the pre-run check had passed, so Glimmer checked against the engine decided | Accepted on the first attempt; review `REPAIR DEMONSTRATED` on `FRESH LIVE` evidence, both arms judged by Glimmer (the second drill, before #146, was `INCONCLUSIVE`) | [41244537695](https://github.com/Expectrail/Expectrail/actions/runs/41244537695), [docs/fallbacks.md](fallbacks.md) |

## Limits

- One public route per request (the smoke route for the game's requests). A review shows what
  happened on that route, not elsewhere in the game.
- A review inherits the verifier's sight. With SAM off the verifier accepts the fix that draws the
  robot inside the ground ([bench/judge](../bench/judge/README.md)); with SAM on it rejects it.
  After a judge ladder fallback, both arms are judged by the judge that decided, Glimmer checked
  against the engine, so the review has Glimmer's sight: the ground is judged on the engine's
  position log ([docs/fallbacks.md](fallbacks.md)).
- The base arm costs one more replay and, with SAM on, SAM's look at its frames; the shared SAM cache
  holds only the clean game's answers.
- Observation models are not guaranteed deterministic: a review run again may differ, and a recorded
  review is evidence of that run, not of a rerun.
- Reviews add traceability, not a trust root: the release candidate's signature does not cover
  `change-evidence.json`.
- Nothing here shows Expectrail makes fixes more likely to succeed: on the development fix matrix both
  conditions fixed all 8 bugs ([bench/fix-matrix](../bench/fix-matrix/README.md)). What it shows is
  which fixes only look right.
