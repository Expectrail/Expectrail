# Opt-in repair after playtest intake (#531)

Current #531 kit: [current model, full-context reservation and $10 cap envelope](live-repair/RUN-SHEET.md). The historical GPT-4o fixer profile below is deprecated and now refused; its offline regression fixtures do not enable it live.

Current #267 behavior: Muse/BYO CLIs stop `fixer-bound-unavailable`. For the
controlled OpenAI GPT-4o sender choose `--repair-agent llm-patch` with an
invocation cap, aggregate Muse cap and model-month ledger. Its pre-send token
reservations and explicit output cap are tested offline; no live provider bill
was measured. See [the price policy and $8.75 cap envelope](llm-patch-spend.md).
The earlier unexecuted hold estimate below is not a live CLI repair quote.

`expectrail ingest REPORT --project PATH` still only reproduces and verifies. Add
`--repair` to hand an approved reproduction to the shipped #433 repair service,
`expectrail.repair.repair`. `agents/loop.py` is the older bundled-game demo; it is
not a generic project API. The implementation follows PRs #441, #447 and #451.

```sh
expectrail ingest report.json --project ./project --repair --json
# Offline, using a saved patch and stand-in observers in tests:
expectrail ingest report.json --project ./project --repair --repair-fixture fix.patch --json
```

Live repair retains the service's existing explicit `EXPECTRAIL_MUSE_USD_CAP`
requirement. `--repair-attempts N` selects its existing 1–10 attempt budget (default
3). Repair runs in the foreground; `--repair --detach` is refused before a job is
created. Proposal options retain their round-two meaning and caps.

Only a completed rejected intake with an approved check failing on all three
anchored base runs can enter repair. The command reads the saved precheck proof
and the job's bound inputs; report text supplies neither checks nor instructions
to the fixer. Generated advisory reproduction, `not-reproduced` and
`anchor-desync` write a repair-run with `repairAttempted: false`. For advisory
reproduction the reason says a person must approve a check first.

The existing loop owns the sandbox, patch application, retries and fresh candidate
verification. The parent job remains rejected. Only the gate's own `decide` rule
and its recorded three-of-three repair evidence can accept a child. The command
returns the existing `expectrail.repair-run/v1`: reproduction kind/check ids,
repair attempted, then the loop's attempts and result. Each candidate attempt
also records its `gateDecision`; the final repair result remains needs-review
when no candidate was accepted. The JSON printed by the command presents intake
metadata first. The saved record uses the existing canonical JSON writer.

## Held-out and advisory boundaries

The service builds its initial and retry briefs with `_public_failures`, selecting
public findings for configured approved spec ids. Child status reasons and
held-out summaries are never retry input. The older demo uses
`agents.escalation.public_feedback`, which allows only public check kinds. The
integration tests use synthetic private route, frame and reason canaries; no
held-out material was read. A held-out-only veto can reject a candidate while the
next fixer receives an empty list of public failures. The service continues to
refuse parent jobs whose held-out policy cannot be replayed through a public
request; this change does not enable private intake.

If trusted candidate verification emits an existing `discovery-run.json` in its
output folder, repair validates that contract and binds findings to the candidate
by `snapshots[].treeSha256`. Any candidate finding ends needs-review with its id
named in `advisoryDiscovery`. Existing advisory `generatedChecks.catches` in the
validated candidate gate record have the same veto, named by spec id. The attempt retains the gate's decision separately;
it is neither accepted automatically nor retried as a failed repair. Malformed or
unbound discovery evidence also stops for review. No discovery generator is added
or launched by repair. The report and the fixer cannot supply that output path;
game files with a similar name do not count as verification output.

## Unexecuted estimate for Sean: one approved report end to end

This is a planning estimate from code, not a paid run or a provider quote.

* `expectrail/repair.py`: default 3 candidates, maximum 10, stopping on acceptance,
  review or budget. `agents/fixer.py`: 15 minutes per live invocation by default.
* `agents/sandbox.py:run_muse_sandboxed` reserves one Muse hold before each CLI
  invocation. `expectrail/spend.py:RESERVE_USD` makes that hold $1. A Muse role cap
  M permits at most `min(attempts, floor(M / $1))` invocations in this foreground
  repair process. This is an invocation reserve, **not a measured token bill**:
  the code supplies no bound on model HTTP requests or actual cost inside a
  15-minute Muse CLI invocation. An exact end-to-end paid-cost ceiling cannot be
  inferred from these caps.
* The intake worker and each fresh candidate worker have their own SAM cap S.
  With A attempted candidates, the configured SAM envelope is at most
  `(1 + A) * S`, before any stricter monthly ledger. Every attempted image request,
  including HTTP retries, reserves $0.0025; video reserves
  `$0.0002 * max(frames, 50)`. The client's default 3 retries mean at most 4 HTTP
  attempts for a logical request; those attempts all count against S. Cached
  observations can reduce requests. A $2 worker cap admits at most 800 image
  attempts (or 200 minimum-size video attempts, or a mixture).
* The base front check is 3 replays of the report route. For R public routes, the
  unchanged parent adds 2R replays. Each candidate adds 2R, plus four more replays
  of each route with a claimed repair (base/head repeated to 3 each), at most 6R.
  Replay count is not model request count: frames, prompts, caching and failures
  determine observer calls.

For one report with A=3, M=$3 and S=$2: at most three fixer CLI invocations,
45 minutes of fixer runtime, $3 in Muse holds, and four SAM worker caps totalling
$8 (at most 3,200 image attempts if every request uses image mode). The resulting
$11 reservation envelope is **not** a guarantee of an $11 provider bill; Muse
invocation holds do not meter its internal token bill. Early acceptance uses one
fixer invocation and two SAM worker caps. No triage or generator call is introduced
on the approved path. An advisory-only report invokes no fixer; `--propose`
retains the existing JIT budget and spec-role cap documented for round two.

No live model, fixer CLI, real engine or paid estimate was run for this round.
