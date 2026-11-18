# Controlled llm-patch request bounds (#267)

## What changed

Applied the previous invocation-cap patch locally, then enabled only the trusted
llm-patch text sender for OpenAI gpt-4o. Extended the strict provider capability
contract with token tariffs, its OpenAI example, writer and reader. The old records
had fixed holds, not token prices; the new $2.50/$10 per million tariff comes from
the public standard pricing table read November 16, 2026, not a guessed hold.

The exact serialized body is reserved at one token per UTF-8 byte plus 1024 and
64 per message for framing; the output is explicitly capped at 4096 tokens.
A documented conservative allowance replaces an exact-tokenizer claim.
The entire invocation cap is held through existing role/month admission. The
shared admission function reserves each physical request before forwarding,
including retry/fallback requests. No refunds. A lock covers send and observation;
reported usage is diagnostic beside each reservation. Unknown tariffs/endpoints,
missing caps/ledger, write failures and provider usage violations stop sends.
Exactly exhausting the invocation cap stops for review before returning a patch.

The operator can select --repair-agent llm-patch for ingest. The existing repair
loop keeps completed/stopped counters, never retries a budget/provider stop and
still delegates candidate decisions to the gate. Muse and BYO CLIs remain refused.

The named SAM + GPT-4o setup in docs/llm-patch-spend.md has a cap-only envelope of
$8.75: 3 x $0.25 fixer holds plus 4 x $2 vision caps. This relies on published
billing and the provider honoring its limits; we cannot enforce an invoice against
a provider violating them. A detected violation prevents later sends, not its
already returned usage. Live conformance, availability and bills are unmeasured.

## What was run

- Before any source edit, with every EXPECTRAIL_* variable removed:
  python3 -m unittest discover -s tests -t . — Ran 4327 tests in 392.008s, OK (skipped=54).
- Final full suite, the same command/environment — Ran 4375 tests in 397.609s, OK (skipped=55).
- python3 -m unittest tests.test_llm_patch_bound — 25 tests, OK. Real local HTTP
  stand-in server; exact bytes, explicit output cap, cap refusal, unknown model,
  concurrency, retries/schema fallback, redirects, usage violations, persistence,
  month admission, controlled helper, existing repair loop and ingest opt-in.
- Targeted boundary/repair/BYO/spend/schema run before the final two tests:
  137 tests, OK (1 skipped). New sender module was rerun after both additions.
- numpy and PIL unavailable via an import guard: 113 tests, OK (1 named skip).
  The initial guard incorrectly raised on find_spec; it was corrected to return
  None there, matching an absent dependency. Both logs are in the handover.
- python3 -m expectrail.capabilities render and check — passed.
- python -m agents.export_scan bench docs README.md apps --paths error — passed,
  zero findings. The prohibited blind-3 directory was excluded by directory
  rename only and restored without reading contents. Repeated after this log.
- git diff --check and patch reconstruction checks — recorded in the handover.

No final-suite failures. Development logs retain the one missing-import failure
that was fixed, and the invalid dependency-harness failures; final reruns passed.

## Not done

No live model/CLI calls, accounts, new credentials, provider bill measurement,
provider-conformance measurement or real repair-quality result. No proof that a
provider cannot ignore its own cap or change its rates. The public pricing table
marks gpt-4o deprecated; live availability was not tested. No live ceiling for
Muse/BYO agent CLIs or arbitrary provider/vision combinations. No --propose quote.
The namespace-dependent gateway test skips by name here because Bubblewrap cannot
create a uid map. The prior proxy's real mitmdump/TLS integration remains unrun.
No push, GitHub comment or PR. Protected gate/anchor files, workflow files,
game projects and approvals were unchanged. Private/blind contents were not read.

## Files

- agents/byo_fixer.py
- agents/fixer_meter.py
- contracts/examples/fixer-invocation-token-price.json
- contracts/examples/provider-capabilities/openai.json
- contracts/fixer-invocation.v1.schema.json
- contracts/provider-capability.v1.schema.json
- contracts/repair-run.v1.schema.json
- docs/capabilities.json
- docs/capabilities.md
- docs/fixer-spend.md
- docs/ingest-repair.md
- docs/llm-patch-spend.md
- docs/new-work/2026-11-16-llm-patch-bound.md
- docs/playtest.md
- expectrail/fixer_budget.py
- expectrail/orchestrator/cli.py
- expectrail/orchestrator/ingest_repair.py
- expectrail/providers.py
- expectrail/repair.py
- expectrail/spend.py
- tests/test_llm_patch_bound.py
