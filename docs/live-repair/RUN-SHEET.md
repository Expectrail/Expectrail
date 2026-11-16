# Sean: one live public fall-through repair

**Not run live.** Scope: one handwritten report, one seeded public bug, one model
(OpenAI `gpt-6.1-sol`). This is not a repair rate or a deployment approval.

**Before dispatch:** review/install the [proposed workflow](../proposals/531-live-repair-workflow.md)
on main after the reviewed code lands. Provision its dedicated Linux runner with
Python 3.12+, `pip install -e ".[contracts]" pillow`, pinned Godot from
`harness/get_godot.sh`, Xvfb/xauth, git/patch and functioning
Bubblewrap. Set `EXPECTRAIL_GODOT_BINARY` to that installed engine. Keep the runner away from fork/PR jobs. In a main-restricted
`live-repair` environment, set `EXPECTRAIL_OPENAI_FIXER_KEY` (OpenAI, exact model
access) and `EXPECTRAIL_META_VISION_KEY` (Meta SAM API). These are separate keys;
none goes in an input or file. Set `EXPECTRAIL_LEDGER_DIR` to a private 0700,
durable runner directory outside checkouts. Keep both month files and locks
across runs; do not reset them or use an evictable cache. No account/key/settings
were created by this work.

**Check the model and quote first:** the [price evidence](price-provenance.txt)
was read November 16, 2026. The local review expires November 23; after that,
a reviewed refresh is required. The default dollar-cap envelope is **$10**:
`1 × $6 fixer + (1 intake + 1 candidate) × $2 SAM`. Other role caps are zero;
completion is capped at 4,096 tokens, including reasoning. SAM is $0.0025/image.
The model's Standard prices are $2/$10 per million input/output tokens. Admission
uses the full 1,050,000-token input-context ceiling and higher $5.50/$16.50 rates
covering documented long-context, cache-write and regional premiums, with
`service_tier=default`. One request reserves exactly **$5.842584**; a second
cannot fit the $6 invocation cap. Thus the tighter request-admission envelope is
**$9.842584**, while $10 is the sum of authorized dollar caps. Holds are not
refunded. Prices/server limits must be honored by the provider; no client can
guarantee an invoice against misbilling. No live conformance/bill was measured.

**The single deliberate step:** in Actions, select **One public live repair**,
choose **main**, leave the recommended caps and **one** attempt, set `confirm`
true, and dispatch once. Do not dispatch from another ref. The workflow prints
its validated plan before loading provider keys. It prepares the public
fall-through patch and PR #551 report, then runs the existing isolated
`expectrail ingest --repair --repair-agent llm-patch` command. No proposal,
new check, model fallback, second fixer or deployment is requested.

**For the run to count:** download the artifact and open its `repair-run.json`.
It must show, in order, approved reproduction, repair attempted, and candidate
acceptance. `playtest-precheck.log` must show the anchor reached and the same
approved ground check failing 3/3 on the base. The invocation must name the
reviewed provider/model, availability check, tariff, each pre-send reservation,
reported usage and no budget/provider violation or advisory flag. The candidate's fresh findings
must say rule `both`, engine and visual agreement, demonstrated repair and
`decision=accept`; every replay must record real Godot and Bubblewrap isolation.
The original approved check bytes must be unchanged. The gate owns acceptance.
A successful job exit or a patch alone is insufficient. The artifact is evidence
for this case only; nothing merges or deploys the patch.

**If it ends needs-review:** keep the artifact and month state. Read the named
stop before doing anything else. Fix setup/availability problems without changing
checks, prices or caps to hide the failure. A known deprecated/withdrawn/expired
record sends nothing; a missing remote model stops at the unbilled metadata GET
before inference. A withdrawal racing that check can still reach the first POST;
its 404/410 stops with `fixer-model-unavailable`, without retry or substitution.
Budget stops, desync, missing reproduction and advisory flags require inspection.
A candidate gate rejection is a failed candidate; the final repair-run still says
needs-review after its one allowed attempt. Never retry automatically. Any later
paid run needs a fresh deliberate dispatch and enough durable month allowance.
