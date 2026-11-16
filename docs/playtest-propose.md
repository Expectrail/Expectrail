# Advisory checks for an uncovered playtest report (#531, round two)

`expectrail ingest REPORT --project PROJECT --propose` tries the existing generated
check path when three anchored base replays give no approved-check failure. The
bundled clean game and platformer mechanics profile are the default trusted
reference; `--clean-project PATH --profile FILE` replace them explicitly. A report
cannot choose either. The reference, profile and optional response are captured
outside the game and included in the request's idempotency digest.

A saved `--proposal-response FILE` uses a stand-in transport in the existing JIT
response shape (`choices` containing JSON text and optional `usage`), with no live
fallback. Without a response, a live proposer is constructed only after the
existing explicit `EXPECTRAIL_SPEC_USD_CAP` passes `spend.require_cap('spec')`;
otherwise the existing generator records `MODEL_UNAVAILABLE` without sending.
If Sean later authorizes a paid run, the existing Spark transport still enforces
its role cap before HTTP. No credentials or cap were provided for a live run here.
The response is not an approved check or a trusted keep result: it passes through
the normal JIT parser and replay assessor. JIT is a repository capability; a minimal
installed wheel without JIT reports generated checks unavailable, never a pass.

The adapter calls `jit.run.generate` with the candidate withheld and an identity
candidate, using captured clean/base snapshots through its existing runner
injection. A hashed `jit-base-snapshot.json` descriptor selects the base snapshot;
it is not a patch applied to the clean game. The record's `basePatchSha256` slot
names this selector's bytes; `playtest-reproduction.json` additionally names both
actual game-tree digests. No proposed fix or candidate bytes reach the model.

The submitted route joins the existing probes as `ingest-report`. Its tick count,
seed and input events are preserved; its id and description are trusted constants.
Actions are checked against the trusted profile before any model invocation.
Only those catalog actions and numbers enter the probe description. Producer,
route-name, route-description and fault-object prose never become model context.
The bug text reaches the model through the existing `untrustedBugReport` field,
including the existing JIT 8,000-character truncation (the request still retains
all 8,192 permitted characters). Model output still uses the bounded compiler and
closed trace language. No bug-family mapping was added.

There is no new keep rule. `jit.run.from_base_alone` reads the completed JIT record:
three clean passes, three base failures, kept by the existing validity rule, and
candidate withheld. That produces `generated-advisory`, not a verdict. The job
stays needs-review, with no fixer call. Other reproduction kinds are `approved`
and `none`; the status and evidence carry the same closed reproduction record.
Queued and preflight-stopped intake jobs start with `none / not-evaluated`.

An anchor mismatch blocks generation. A stable approved failure continues to the
existing gate without calling the proposer. Unstable approved failures do not
trigger proposal; absence of approved failures may trigger advisory investigation
also when the approved set has gaps or no applicable check, without upgrading
those gaps to passes. None of this implements the remaining counting/clearance
conditions of #271, human approval, a fixer, or a held-out feedback path.

## Recorded demonstration

A hand-written report uses the public `bugs/reported/body-flip.patch` on a
committed disposable copy. Its walk-left/right route has 240 ticks and its anchor
is at tick 9, before the first left press at tick 10. Pinned Godot
`4.7.2.stable.official.ed1daf0bf` recorded a facing/movement mismatch fraction of
0.7534. The existing approved ground check passed three times; the round-one
path ended `not-reproduced`.

The normal subprocess CLI with `--propose --proposal-response` on the same real
report kept a stand-in model's direction-agreement check on `ingest-report`:
clean passes 3/3, base failures 3/3, unchanged candidate failures 3/3. The result
is needs-review with `generated-advisory`, not accept or reject. The response was
chosen by hand, not produced by a live model: this demonstrates wiring and the
mechanical keep rule, not model proposal quality or a measured reproduction rate.
The raw report, response, manifests, traces, status, worker logs and JIT record are
in the handover. No paid API or fixer was called.

## Spend estimate for Sean — not executed

One report is in this round's evidence set: `handwritten-body-flip`. The other
builder's report bundle and `docs/playtester-results.md` were not on the starting
main, so no larger count is invented. The formula applies when that bundle arrives.

The code's caps (`jit.intent` and `jit.run`) give one proposer request per eligible
report, no revision in this path, at most eight checks and four new probes, and a
30,000-completion-token reservation. This report's estimated prompt is 2,897 tokens.
With the existing **assumed**, not published, prices ($1/million input tokens,
$4/million output tokens), the proposer reservation is:

`2,897 × $1 / 1,000,000 + 30,000 × $4 / 1,000,000 = $0.122897`.

For the one report: one potential request, $0.122897 proposer reservation and a
$2 total JIT budget envelope, including trace replay pricing. For N eligible
reports: N requests, about N × $0.122897 at this prompt size, and N × $2 envelopes.
Anchor-vetoed or approved-reproduced reports make zero proposer requests.
No SAM or fixer call is in this generated trace path. Existing approved-check
vision, if separately configured later, is outside this proposer estimate.

One kept single-probe check takes nine trace replays in the existing path (three
reference, base and unchanged candidate runs). The JIT ledger prices runner time
at $0.008/minute. Its longest-seen replay reservation can be exceeded by the final
replay's own cost; the $2 envelope is the existing stopping policy, not a cloud
bill or a claim of a hard wall-clock bound. Stand-in token usage in the recorded
JIT spend is simulated accounting, not actual model spend. Actual live requests:
zero. Sean must separately authorize a paid run and configure its existing role cap;
that live binding was tested only with a patched cap and stand-in transport here.
