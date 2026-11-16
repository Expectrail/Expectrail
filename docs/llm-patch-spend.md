# A controlled request ceiling for llm-patch (#267)

Current #531 kit: [current model, full-context reservation and $10 cap envelope](live-repair/RUN-SHEET.md). The historical GPT-4o fixer profile below is deprecated and now refused; its offline regression fixtures do not enable it live.

`llm-patch` builds its requests in trusted host code. It now reserves a maximum
before every send. Muse Code and BYO agent CLIs still stop with
`fixer-bound-unavailable`; their processes choose their own requests. No live
model, bill, provider conformance or repair quality was measured for this change.

## The price and input bound

The capability records previously contained request **holds**, not token tariffs.
The strict `expectrail.provider-capability/v1` contract now permits `tokenPrices`.
The OpenAI record names `gpt-4o`, with uncached input at **$2.50 per million
tokens** and output at **$10 per million tokens**, or 2,500 and 10,000 nanoUSD per
token. These prices were read on November 16, 2026 from the public
[standard text pricing table](https://developers.openai.com/api/docs/pricing),
without making a model call. Cached input is reserved at the higher uncached
rate. The old $0.05 request hold is not used as a tariff. There is no newly
assumed price for another provider or model. The table labels GPT-4o deprecated;
live model availability was not tested.

Only OpenAI's HTTPS `api.openai.com/v1/chat/completions`, model `gpt-4o`, and text
messages are enabled. Unknown models, endpoints and unsupported billable shapes
are refused. No image, tool execution, audio, reasoning-model tariff or service
tier is enabled by this policy. Redirects and environment HTTP proxies are
disabled for this sender.

The sender serializes the complete JSON body once. Let B be its UTF-8 byte
length and N its message count. It reserves input tokens **I = B + 1024 + 64N**.
Byte BPE starts with bytes and merges them, so each text byte contributes at
most one token. Counting the whole JSON includes roles, escapes, schema and
other structural bytes that the API normally does not tokenize as message
text. Non-ASCII characters are escaped by the serializer and overcounted.
The extra framing allowance exceeds the published GPT-4o text-message recipe
(3 per message plus 3 for the reply) by **1021 + 61N tokens**, before that JSON
surplus. This is an upper bound, not an estimate with a percentage error or a
claim of exact tokenization. See the
[OpenAI token counting recipe](https://cookbook.openai.com/examples/how_to_count_tokens_with_tiktoken).
Schema instructions are covered by their serialized bytes and the extra
allowance; server-private or changed framing is a provider-conformance risk.

The wire body explicitly sets `max_tokens=4096` for the fixer. For a request
with output cap O, the reserved maximum is exactly **2500I + 10000O nanoUSD**.
Integer arithmetic avoids rounding down a request. The invocation dollar cap is
rounded down to nanoUSD. The record stores the byte count and SHA256, token
bounds, tariff and source, and diagnostic reported input/output usage beside
each reservation; it stores no request text or credentials.

## Admission and stops

Before any request, the entire invocation cap F is held through the existing
`spend.hold('muse', usd=F)`. It must fit the aggregate Muse role cap M. The
existing locked model-month ledger reserves M once per process/month. This
controlled path requires that ledger. Per-request reservations spend the
already held F, without double-counting it against the month.

Each physical HTTP attempt reserves again, including retries and schema
fallbacks. Nothing is refunded, including errors, timeouts and disconnects.
A request that cannot fit is not sent. One invocation lock serializes admission,
sending and response observation; concurrent callers cannot pass a budget stop
or usage violation. A durable-write failure stops before a new send. The record
has a separate safety ceiling of 1,024 admitted requests.

Usage above either reserved input or capped output is recorded and stops the
invocation as `fixer-provider-violation`. Missing valid success usage also stops
it. The existing repair loop returns needs-review without verifying a partial
patch or retrying the fixer. `fixer-invocation-cap` likewise means a budget stop,
not a failed repair. Exactly exhausting F also stops for review before a patch
is returned; it does not become an accepted repair. Completed attempts with
unused budget retain their counters too.

This is an enforced **admission** ceiling using the provider's published billing
and server-side output cap. Our code cannot stop a provider from misbilling or
ignoring its output cap; a violation response can already represent more usage
than reserved. Detection prevents later sends, not that earlier provider
violation. No client-only implementation can guarantee an invoice against that
behavior. Live conformance remains unmeasured.

## One report: Sean's cap-only envelope

For one eligible **approved-check** reproduction, without `--propose`, choose
OpenAI `gpt-4o` for `llm-patch`, and Meta `sam-3.1` image observation throughout.
The latter price is the existing Meta capability record's **$0.0025/image**,
also enforced by `agents.sam_observations`. This quote excludes other visual
backends, raw host judge utilities, generated checks and their model holds.

Set these caps before a future authorized run (none was run here):

```sh
export EXPECTRAIL_FIXER_PROVIDER=openai
export EXPECTRAIL_FIXER_MODEL=gpt-4o
export EXPECTRAIL_FIXER_API_BASE=https://api.openai.com/v1
export EXPECTRAIL_FIXER_INVOCATION_USD_CAP=0.25
export EXPECTRAIL_MUSE_USD_CAP=0.75
export EXPECTRAIL_VISION_BACKEND=sam
export EXPECTRAIL_SAM_MODEL=sam-3.1
export EXPECTRAIL_MODEL_API_BASE=https://api.meta.ai/v1
export EXPECTRAIL_SAM_USD_CAP=2
# Set EXPECTRAIL_MODEL_MONTH_LEDGER and EXPECTRAIL_VISION_MONTH_LEDGER to durable
# files outside the checkout. Supply separately provisioned keys in the environment.
expectrail ingest report.json --project PROJECT --repair --repair-agent llm-patch --repair-attempts 3 --json
```

At most three fixer invocations hold $0.25 each: **$0.75**. One intake worker
plus at most three fresh candidate workers each have a $2 vision cap: **$8**
(800 image attempts per worker). The intake cap includes all its base replays;
retries do not get another cap. The exact worst-case envelope **from these caps
alone is $0.75 + $8 = $8.75**, under the published billing policy above.
In general it is `min(A*F, M) + (1+A)*S`, with configured attempts A and SAM cap S
when all A invocations fit. Request granularity, earlier stops, caches and
accepted candidates can make actual reservations smaller. The invocation sends
at most F; it does not deliberately spend the remainder to reach F.

This is a price-based bound, not a measured run cost or a promise of a useful
patch. The gate still owns every candidate decision. A generated advisory check
alone cannot start repair, and report text cannot select the trusted agent,
model, cap, tariff, check or decision.

## Recorded tests

`tests.test_llm_patch_bound` uses the real HTTP sender with a local stand-in
server. It covers the exact body hash/output cap, no send over the remaining
cap, unknown model/endpoint refusal, request concurrency, retries, schema
fallback, redirect refusal, usage violations, missing usage, write failure,
month/aggregate admission, the llm-patch entry point and the existing repair loop.
Socket rerouting is internal test code; no production endpoint override enables
an unpriced server. Existing tests cover CLI refusal and repair eligibility.
All of this is offline evidence. The local stand-in's paid cost is $0.
