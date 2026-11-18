# Repair after a reject: the remaining #433 paths

This change builds on the P0 audit at main
`ec0919b60c03abf033ef79a996880300658e6887`; the assigned branch starts at
`ba050a770f6010c430b51c6a93cf1e81d2cccff5`. The audit patch is included as a
prerequisite. Nothing here was run against a paid model or published to GitHub.
**Part of #433**, not a closure: Sean's live measurement and site/workflow
publication remain. The older audit is a historical inventory, not current status.

## Agent work delivered

| Original gap | Implementation and falsifiable test |
| --- | --- |
| Bounded agent selection through automatic repair | `verify --auto-fix --auto-fix-agent llm-patch --auto-fix-usd-cap 6`; app selector, request schema/example, shared producer and worker reader. `tests.test_433_remaining.BoundedAutoFix` and `AppAgent` verify the selected source reaches the existing loop, the old default remains Muse, unknown agents/capless use are refused and an offline patch cannot be relabelled with an agent option. |
| Same held-out suite on fresh candidate jobs, without exposing it to the fixer | `verify --with-heldout` binds only the suite named by operator environment `EXPECTRAIL_HELDOUT_DIR`. The request contains a digest and consent bit, never a supplied private path. `EXPECTRAIL_HELDOUT_VISION=1` is additionally required before held-out frames can reach the existing visual observer. Every child keeps that binding. `HeldOutChildren` authors a synthetic suite, proves its real gate veto survives both children, and checks requests/retry feedback/workspaces for canaries. Missing/changed context or withdrawn visual consent refuses before a fixer starts. No actual held-out material was used. |
| Literal command real-engine CI proof | `tests.test_replay_sandbox.RepairCommandsRealEngineTest`: verify → repair, verify → auto-fix, and a never-successful fixture. The existing **seeded-bugs** job collects the module with `EXPECTRAIL_SANDBOX_TESTS=required`, so those tests require real Godot and Bubblewrap; no workflow edit. Outside that lane they skip by name unless explicit local diagnostic mode is selected. Game and approved-check source bytes are unchanged; the public wait route is copied to both policy snapshots. |
| Run it accepts honest provider-only provenance | Repair-run schema/example/writer now name `providerOnly: true` only for controlled llm-patch execution and bind each copied invocation counter by SHA-256. `repair_provenance` reads completed token-priced admissions, provider usage and aggregate holds. The Run it reader refuses fixture/recorded sources, missing/changed/stopped/violating counters and unbound legacy provider-only records; it never changes `sandboxed: false` to true. `ProviderOnlySample` exercises the fresh gate with stand-in records. The fourth card remains unpublished. |
| A trusted draft-PR publisher | `python3 -m tools.repair_draft`: authenticates the current labelled head's published reject with the existing authorization code; checks the latest repair run and unchanged base/merge/head workflow; checks the downloaded ZIP against GitHub's digest; validates repair/patch/provenance; recomputes the original game tree from bounded regular Git blobs; applies the text patch to an isolated temporary index with no hooks/filters/worktree; creates only game-scoped changes, a new branch and a **draft**. `tests.test_repair_draft` uses a GitHub stand-in, including changed head/workflow, altered plan/archive, review flags, out-of-scope paths and a mid-publication head move. No real GitHub write occurred. |
| One deliberate literal live case, with the existing bound | `python3 -m tools.repair_live_case` prints the existing kit's plan and sends nothing. `--run --mode manual` runs literal verify then repair; `--run --mode auto` runs literal verify with bounded auto-fix. Both allow one attempt in this run sheet, delegate to the existing CLI, preserve its parent reject and report its existing repair-run. `tests.test_repair_live_case` tests default no-send, cap/model selection, command shape and no standalone repair unless the original job rejects. |

No second fixer, generator, retry rule, sandbox or gate decision is introduced.
Muse and BYO agent processes still stop with `fixer-bound-unavailable`. Only the
already-controlled llm-patch sender can make live fixer requests under its
reviewed model/tariff, explicit output limit, invocation reservation and month
ledger. Model withdrawal/expiry/unknown price never selects another model.

## What the proof means

The three local real-engine runs used **Godot 4.7.2**, real CLI subprocesses and
the public fall-through bug. Direct repair and auto-fix each produced a distinct
child gate accept with repair demonstrated; the rejected original stayed reject.
The bad fixture produced two distinct child rejections and needs-review on
attempt exhaustion. Source was unchanged. The [small run summary](measurements/433-remaining.json) records all three cases
and the five guard-removal red runs. Full logs are in the handover.

The visual observer in these offline command tests is explicitly **trace-backed
fixture data, not independent vision**. It is installed only by a test bootstrap,
not by a production configuration flag. These tests prove the command, engine,
patch and existing gate wiring. They do not measure a live fixer's quality,
vision accuracy or a repair rate. The first diagnostic attempt supplied an
invalid observer name; the gate correctly refused that fixture. Its corrected
rerun retained the same accept/reject assertions.

This machine's Bubblewrap probe fails at UID mapping (read-only filesystem).
The local runs therefore say **isolated: false**; no sandbox result is invented.
The existing CI job is the required isolated run, after Sean pushes this patch:

```sh
EXPECTRAIL_SANDBOX_TESTS=required python3 -m unittest tests.test_replay_sandbox.RepairCommandsRealEngineTest -v
```

The new test and helper load without numpy or PIL. No existing assertion was
removed or weakened. The engine test edit adds three cases to that already-collected module.
The existing bounded-fixer test also gains the new exact provenance object and
counter-digest assertions; its refusal/no-verification/no-retry checks stay intact.

## Private context is an operator input

An operator may use `verify ... --with-heldout` only after provisioning a trusted
suite outside **both** selected checkouts and setting `EXPECTRAIL_HELDOUT_DIR`.
No project config, bug-report string or browser path can select that directory.
The worker validates and snapshots only the manifest and named regular route
files, then calls the existing gate. It checks the binding again after the run;
a changed suite cannot silently accept. Held-out replay artifacts are deleted
by the gate; only counts reach its findings. A repair with no public failing
sentence still cannot start a fixer. A private veto can prevent acceptance,
but no private route, per-check result, frame or reason enters retry evidence.
Only the overall gate decision and the existing public-failure projection are
used. Visual consent is off by default and cannot be enabled by the request alone.

## Draft publication is data handling

The [complete publisher workflow proposal](proposals/433-draft-publisher.yml.txt)
is text for Sean to install, not an active workflow. It listens for completion
of the existing labelled fixture-repair workflow, or an explicit manual dispatch.
It checks out **main only**, never candidate code. Its write token is available
only to the publisher step; it has contents-write, PR-write and actions-read,
no model key and no game/display tools. It targets the public Expectrail repository;
GitHub documents that its public check-run reads need no Checks permission.
Private-repository use would need a separate permission review. The workflow shape test also checks the
installed file if Sean installs it at the documented name.

The tool defaults to preparation without API writes. `--send` is deliberate.
Serialized plans are audit data, not publication authority: publishing requires
an unchanged in-memory plan produced from the authenticated artifact. The original
repair record, source label and immutable head remain named in the draft. An
offline fixture must stay labelled fixture, even if its gate accepted.

The publisher rechecks authorization before every write and refuses an observed
head/base/attempt change. GitHub has no atomic “compare original PR head and
create another PR” operation: a change after the final check can leave a stale
draft based on the named old head. It is never merged or given clearance. Review
that exact head, rerun verification or close the stale draft. Existing branch/PR
collisions are refused, never overwritten; a partial API failure may leave
unreferenced blobs or a review branch. Hosted API permissions and the installed
workflow have **not** been measured here.

## Sean: each remaining action

Each row is one operator action, not something the builder performed. Setup rows
that the existing live-repair kit already satisfies need no duplicate work.

| Action | Exact operation |
| --- | --- |
| Land and validate the code | Push the reviewed `chatgpt/433-remaining` change and inspect the existing `seeded-bugs` job's three new literal-command tests before merging. |
| Install the draft publisher | Add [433-draft-publisher.yml.txt](proposals/433-draft-publisher.yml.txt) verbatim as `.github/workflows/expectrail-repair-draft.yml` on main after reviewing its write-token boundary. |
| Permit draft creation if currently disabled | In Settings → Actions → General → Workflow permissions, review and enable GitHub's “Allow GitHub Actions to create and approve pull requests” switch. GitHub combines those permissions; this publisher never reviews/approves or merges a PR. If that broader platform switch is unacceptable, do not enable it; supply a separately reviewed scoped app instead. |
| Enable the existing opt-in fixture path | Run `gh variable set EXPECTRAIL_CI_AUTOFIX --repo Expectrail/Expectrail --body true`. The existing `EXPECTRAIL_CHECKS_APP_ID` must already identify the clearance publisher. |
| Exercise the automatic draft path | Add the `expectrail-autofix` label once to a current-head rejected PR containing the public seeded bug; inspect the resulting fixture repair artifact and draft. Keep its run URL and artifact digest. This uses no model budget. |
| Install the literal live workflow | Add [433-live-repair-workflow.yml.txt](proposals/433-live-repair-workflow.yml.txt) as `.github/workflows/one-literal-repair.yml` on main after reviewing the existing live-repair runner/key/ledger boundary. |
| Provision missing runner prerequisites | Provision the dedicated `expectrail-live` Linux runner according to [the existing run sheet](live-repair/RUN-SHEET.md), including functioning Bubblewrap, pinned Godot, Xvfb and persistent private month state. Do not use a fork/PR runner or an evictable cache for that state. |
| Provision the fixer key if absent | Store the OpenAI key for the exact reviewed model as `EXPECTRAIL_OPENAI_FIXER_KEY` in the main-restricted `live-repair` environment. No key goes in an input, file or message. |
| Provision the vision key if absent | Store the separate Meta SAM key as `EXPECTRAIL_META_VISION_KEY` in that same environment. |
| Set the engine location if absent | Set repository variable `EXPECTRAIL_GODOT_BINARY` to that runner's already-installed pinned engine path. |
| Set durable state location if absent | Set repository variable `EXPECTRAIL_LEDGER_DIR` to the runner's private persistent ledger directory outside checkouts. Retain both month files and locks. |
| Recheck the quote before spending | Run `python3 -m tools.repair_live_case --mode auto` on main and review the printed model/tariff. The recorded review expires November 23, 2026; an expired/withdrawn record refuses instead of falling back. |
| Measure auto-fix once, only after approving the budget | Dispatch **One literal repair case** on **main**, mode **auto**, one attempt, confirm true, recommended invocation/aggregate/vision caps **6 / 6 / 2**. Keep the complete artifact even on needs-review; do not silently retry it. |
| Measure the standalone live command if both live entry points are required | Dispatch the same workflow once with mode **manual**, under a separately authorized budget. This is a second run, not covered by the first run's cap. |
| Publish a genuine accepted repair sample | After reviewing a successful live record and its exact saved vision answers, copy it and all digest-bound counters/patches to the [documented Run it paths](run-it.md), then set the real and example sample manifests' `repairRecorded` flags. Do not use a schema example or fixture result. |
| Verify the visible sample | Open the deployed fourth Run it card and check that its fresh gate result, attempts timeline, winning diff and review label appear; retain the deployment/run link. |

The default **per-run** authorized envelope is still **$10**:
one $6 fixer invocation envelope plus $2 original-worker vision and $2 candidate
worker vision. The existing full-context request admission reserves $5.842584,
so the tighter request-admission envelope for this one-attempt model is
$9.842584. Prices and provenance are the existing
[reviewed capability excerpt](live-repair/price-provenance.txt), not a new price
assumption. Reservations are not refunded. Two separately dispatched modes each
need their own authorization; no live run was made here.

For a run to count, the original must reject; the existing repair-run must show
a repair attempted and its fresh candidate gate accept under `both`, with repair
demonstrated, real isolation on every replay, unchanged approved check bytes,
correct provider-only provenance, no budget/provider violation and no advisory
discovery flag. A patch, a successful job exit, fixture acceptance or a draft PR
alone is insufficient. Needs-review remains review: preserve the record and
inspect the named stop without weakening checks, changing provenance or raising
caps to hide it.

The two live dispatches above are separate actions. These are the literal
commands for Sean **after** he installs/reviews the workflow and authorizes each
budget; they were not run here:

```sh
gh workflow run one-literal-repair.yml --repo Expectrail/Expectrail --ref main -f mode=auto -f confirm=true -f fixer_invocation=6 -f fixer_total=6 -f vision=2 -f attempts=1 -f output_tokens=4096 -f disabled_caps='{"spec":0,"triage":0,"glimmer":0}' -f month_caps='{"model":200,"vision":200}'
```

For the separately authorized standalone command measurement, run that exact
command once with `-f mode=manual` instead of `-f mode=auto`. If the first run
ends needs-review, retain its artifact and resolve the named stop before deciding
on any further dispatch. Neither command creates or approves a check.
