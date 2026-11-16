# BYO smoke: an output limit before any text (#562)

The smoke asks each configured text provider to reply with one word. It only
checks that text arrived; it neither judges that text nor verifies a game.
No key is a named skip. A request error or an answer cut off before any text is
a failure and exits nonzero.

## What the recorded failure proves

| Scheduled run | Recorded outcome for Baseten / Muse Spark Open |
| --- | --- |
| [Nov 14, 43603762738](https://github.com/Expectrail/Expectrail/actions/runs/43603762738) | answered; job succeeded |
| [Nov 15, 43726388952](https://github.com/Expectrail/Expectrail/actions/runs/43726388952) | no text, `finish_reason=length`; job failed |
| [Nov 16, 43914762984](https://github.com/Expectrail/Expectrail/actions/runs/43914762984) | answered; job succeeded **before this change** |

The Nov 15 job checked out
`ccb58ef2105c707666c80334044dbae448b56320`. Its
[`agents/byo_smoke.py`](https://github.com/Expectrail/Expectrail/blob/ccb58ef2105c707666c80334044dbae448b56320/agents/byo_smoke.py)
requested **256 output tokens**. The shared sender put that value in
`max_tokens`. The log records no usage counts, reasoning counts or response body.
It cannot prove how many tokens were billed or how many were reasoning tokens.

Comparing Nov 14's `cb1fc856c17dc64da494c12d9d582af3f1ff6ca7` with Nov 15's head:
`agents/byo_smoke.py`, `expectrail/providers.py` and the smoke workflow have
identical Git blobs. The relevant `git log` contains the new provider-capability
record (`0a844e206fd3d27613124a1c74c501a3cb2b4f90`); the smoke did not read that
record then. There was **no request-path code change** between those two runs.
Other project work did merge. The handover contains the blob comparison and log.

Baseten's [reasoning documentation](https://docs.baseten.co/inference/model-apis/reasoning.md),
read Nov 16, says Muse Spark Open **always reasons**, has no off switch, and that
`max_tokens` includes reasoning. It also says `reasoning.max_tokens` is enforced
only for a different model. Thus reasoning consuming the 256-token allowance
before final text is the likely explanation. The recorded run does not establish
its exact internal token split, a model deployment change or a provider defect.
The successful Nov 16 run does not prove this patch works: it predates it.

## Named failure, shared by the readers

The shared sender and saved-response text reader raise `OutputLimitReached`,
with code `output-limit-before-text`, for empty/whitespace text plus
`finish_reason=length`, or the Messages API's `stop_reason=max_tokens`.
Reasoning blocks do not count as answer text. For example:

```text
output limit reached before any text: 2048 tokens (requested limit), finish_reason=length
```

The requested limit is not presented as measured usage. When the provider
supplies output/reasoning token counts, those are separately named. A saved
response with no request limit says `request limit not recorded`. No reasoning
content, key or complete model response is printed for this outcome.

The smoke records `result: output-limit`, counts it as failed, reports the
output-limit count and exits 1. HTTP errors and empty refusals remain ordinary
failures. Check drafting and fixers receive the same explained exception;
a saved truncated reply cannot become an empty candidate or a JSON/None crash.
Legacy triage reports it as an offline fallback, not a successful model answer.
The change concerns **no text**: a nonempty reply retains the existing smoke
semantics, including when its wording is a refusal. The smoke is not a verdict.

## The affected smoke's allowance and price

The [Baseten capability record](../contracts/examples/provider-capabilities/baseten.json)
now has a smoke-only `textSmoke` section. Its
[schema](../contracts/provider-capability.v1.schema.json), example, writer and
reader are covered together. The old record contains a $0.05 triage hold, which
its schema explicitly distinguishes from a vendor bill; it cannot price this
smoke. The new tariff is separately sourced. This does not authorize Baseten for
the bounded fixer and does not change that hold.

For the exact recorded model and endpoint, one smoke invocation permits:

- **1 HTTP attempt**, including errors; no retry or fallback request.
- **256 input tokens**, enforced by the documented `truncate_prompt_tokens` field.
- **2,048 output tokens**, reasoning included, enforced by `max_tokens`.

The [model page](https://www.baseten.co/library/muse-spark-open/), read Nov 16,
lists uncached input at **$1.25 per million tokens**, cached input at $0.15 and
output at **$4.25 per million tokens**. The record uses the higher uncached input
rate: 1,250 nanoUSD per input token and 4,250 per output token. Therefore the
maximum token charge at those recorded rates and documented limits is:

```text
(256 × 1,250 + 2,048 × 4,250) nanoUSD = $0.009024 per Baseten smoke invocation
```

That is a token-charge bound, not a measured bill or a guarantee about taxes,
credits or later price changes. It relies on the provider honouring the
[documented API limits](https://docs.baseten.co/reference/inference-api/llm-openapi-spec.json).
Offline tests prove which fields and attempt limit we send; the new combination
has **not been run live**. More room makes truncation less likely, not impossible.
A later truncation still fails with its named reason, never retries to a pass.

Other providers retain 256 output tokens and now also get one attempt. Their
prices are not inferred from Baseten's record; $0.009024 is **not** a price for
the complete multi-provider job. Duplicate CLI provider names do not multiply
requests. An overridden Baseten model or endpoint without a matching smoke
record is refused before sending. No new keys, spending environment or workflow
permissions are needed.

The existing no-key preflight prints the recorded plan without sending:

```sh
python3 -m agents.byo_smoke --list --provider baseten
```

## What remains

No workflow edit is required: the existing preflight and live step use the
updated code. No workflow was dispatched and no paid request was made for this
change. Sean can inspect the next scheduled run's conclusion and provider row;
this remains **Part of #562** until the new path has recorded live evidence.
