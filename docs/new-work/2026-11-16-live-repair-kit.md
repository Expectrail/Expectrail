# One deliberate public live-repair kit (#531)

## What changed

Applied the under-review llm-patch bound patch locally on the branch containing
merged #557. Recorded a current OpenAI gpt-6.1-sol profile, its public price/model
excerpts and API reference, lifecycle status and seven-day review expiry. The old
GPT-4o fixer profile is deprecated and refused. Known inactive/expired records
send nothing; a fail-closed, unbilled metadata GET refuses remote withdrawal
before inference. A withdrawal racing the check becomes a named 404/410 stop,
with no retry, model or price fallback. We cannot predict that race without a
request, and did not claim otherwise.

The current model reserves its whole published 1,050,000-token input context,
not an uncalibrated framing estimate. Exact bytes/hash and the byte bound remain
recorded. Standard base prices are $2/$10 per million input/output; reservations
use $5.50/$16.50 including long-context, default 30-minute cache-write and regional
uplifts. The Chat Completions reference states the 30-minute default for this
literal-text request shape. A general 12-hour table tier is not selected here.
Explicit max_completion_tokens includes reasoning, with service_tier=default.
The per-request maximum is $5.842584 at 4096 output tokens; the recommended $6
invocation cap admits one request. The default authorization envelope is $10
(fixer $6 plus two $2 SAM workers); its tighter request-admission ceiling is
$9.842584. Prices and server limits must be honored by the provider. No invoice
or live conformance guarantee was inferred from a stand-in.

Added a default-plan-only source kit; --run prepares only the known public
fall-through bug and PR #551 handwritten report, then invokes the real isolated
ingest --repair --repair-agent llm-patch command. No new fixer, sandbox, retry,
reproduction, approval or candidate-decision rule. Fresh per-run SAM caches and
full confirmation prevent probing settings or offline answers crossing into a
live run. The existing bounded source collector now orders project settings and
entry-scene dependencies before ancillary files, so the actual player mask and
ground layer reach the existing fixer within its original context limits.

A real capture exposed logical-versus-physical viewport metadata. Corrected the
harness writer to record window pixels; the existing reader already expects
captured pixels. Every recorded trace viewport is checked against its real PNG.
No game or protected verifier source was edited.

Complete proposed manual-only/main-only workflow text lives in docs/proposals,
with least permissions, environment/runner restrictions, cap inputs, durable
external month ledgers and artifacts. It is not installed or dispatched. The
one-page run sheet states the setup, single dispatch, budget, success criterion,
needs-review handling and limits before any live run. Capability docs updated.

## What was run

- Baseline, all EXPECTRAIL_* variables removed: Ran 4379 tests in 424.081s, OK (skipped=55).
- Final full suite, the same clean environment, after the engine rehearsal:
  Ran 4484 tests in 816.807s, OK (skipped=44).
- The preceding concurrent full run had one error in
  tests.test_ingest_generated.GeneratedIngest.test_always_passing_and_wrong_model_checks_do_not_reproduce
  (empty CLI JSON output). It passed alone in 0.524 seconds, then in the final
  full run. No change or skip was made to that test. All logs are retained.
- Final real CLI rehearsal: real Godot 4.7.2, Bubblewrap, localhost fixer/vision
  servers, fresh per-case caches. Accepted repair: gate accept by rule both,
  19 replays, 1 fixer POST and 158 vision POSTs. Still-broken candidate: gate
  reject, final needs-review after the one allowed attempt, 11 replays,
  1 fixer POST and 16 vision POSTs. Mid-run cap: needs-review, no candidate job,
  7 replays, one fixer POST, its retry refused, 8 vision POSTs. Each case also
  has one unbilled localhost metadata GET. No external inference call or spend.
- All 37 final replays record Bubblewrap network isolation. Every HTTP POST
  reconciles to its pre-send reservation; each fixer body hash matches its
  counter. Final evidence validation: 3 tests in 0.277 seconds in the first
  run; the final records were validated again (see final log). Raw reports,
  requests, budgets, traces, manifests and final repair-run records are in the
  handover, with selected real frames and evidence/index.html.
- Current model/budget, historical bound, spend and schema focused run: 63
  tests, OK. After adding source-context coverage, 30 context/bound tests, OK.
  numpy and PIL absent via an import/find_spec guard: 129 tests, OK, 4 named skips.
- Capability render/check and 48 capability tests passed. Proposed YAML parses:
  dispatch only, main/repository/event/confirmation guard, contents:read, eight
  inputs. No GitHub workflow execution or settings validation was claimed.
- The required export scan and patch reconstruction checks are recorded in the
  handover. The prohibited blind-3 directory is excluded by directory rename
  only and restored without reading contents.

Development iterations retained: missing virtual display/nested proc setup,
unsupported nested schema format keyword (corrected), an exact model-list
expectation updated for the new model, and insufficient source context caught
by a test before the final collector ordering. Earlier rehearsal drafts used a
shared cache; the final run uses its own fresh caches. None is live-model evidence.

## Not done

No live model, authenticated live availability, conformance, invoice, repair-rate
or model-quality measurement. The fixer patch and vision answers are stand-ins;
37 real engine replays do not turn them into model evidence. Only one public bug
and one requested fixer model are prepared; no general repair/visual correctness,
held-out performance, generated-check quality or deployment claim. The model/price
review expires November 23 and needs a reviewed refresh after that. No fallback.
No workflow file, environment, secret, account or runner was created/configured;
no dispatch, push, comment or PR. No protected verifier, game, approval or blind
content changes. No private/held-out content read. The artifact is a review kit,
not authorization to spend or merge a candidate.

## Files

- agents/byo_fixer.py
- contracts/examples/fixer-invocation-current-model.json
- contracts/examples/provider-capabilities/openai.json
- contracts/fixer-invocation.v1.schema.json
- contracts/provider-capability.v1.schema.json
- docs/capabilities.json
- docs/capabilities.md
- docs/fixer-spend.md
- docs/ingest-repair.md
- docs/live-repair.md
- docs/live-repair/RUN-SHEET.md
- docs/live-repair/price-provenance.txt
- docs/live-repair/rehearsal.json
- docs/llm-patch-spend.md
- docs/new-work/2026-11-16-live-repair-kit.md
- docs/playtest.md
- docs/proposals/531-live-repair-workflow.md
- docs/proposals/531-live-repair-workflow.yml.txt
- expectrail/fixer_budget.py
- expectrail/providers.py
- expectrail/spend.py
- harness/godot/expectrail_harness.gd
- tests/test_live_repair_kit.py
- tests/test_llm_patch_bound.py
- tests/test_spend.py
- tools/live_repair_kit.py
- tools/live_repair_rehearsal.py
