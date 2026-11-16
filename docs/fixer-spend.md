# What a fixer invocation can spend (#267)

Current #531 kit: [current model, full-context reservation and $10 cap envelope](live-repair/RUN-SHEET.md). The historical GPT-4o fixer profile below is deprecated and now refused; its offline regression fixtures do not enable it live.

**Muse Code and BYO agent CLI dollar ceilings remain unestablished; those live
fixers stop `fixer-bound-unavailable`.** Controlled `llm-patch` now has a recorded
OpenAI GPT-4o tariff, pre-send token reservations and an explicit output cap.
See [the controlled sender, limits and $8.75 cap envelope](llm-patch-spend.md).
Offline fixture patches still work. No live model or CLI was called.

## The outbound audit

| Path | Where traffic can leave | What counted it before this change | Current fixer behavior |
| --- | --- | --- | --- |
| `agents.fixer.run_fixer`, saved patch | No model process | No model spend | Unchanged offline patch path |
| `agents.sandbox.run_muse_sandboxed` | Calls `run_muse`; previously one $1 hold before a whole invocation | One invocation, not its HTTP requests/tokens | Requires `EXPECTRAIL_FIXER_INVOCATION_USD_CAP`, then refuses unsupported live pricing before launcher warm-up or a gateway |
| `warm_muse` | Host-side `muse --version` may install/update through the launcher's network | No request meter; its environment excludes model keys | Not reached by a refused fixer invocation |
| Muse in Bubblewrap, gateway on | In-sandbox TCP bridge → bound Unix socket → host `UnixBridge` → mitmdump → upstream | Gateway logged completed/error flows, no token/billing meter | The prototype adds host-side pre-send admission; no production tariff enables it |
| Muse with gateway off, or unsandboxed | Direct host network; proxy environment variables can be ignored | The $1 invocation hold only | Fixer wrapper cannot select this path; legacy raw `run_muse` remains a host judge/trust-probe API with soft holds |
| BYO agent CLI | `run_byo_agent` → `run_sandboxed`; gateway off shares the host network, gateway on uses the same socket/proxy | No invocation dollar maximum | Refused before provider/key/command preparation |
| BYO `llm-patch` | Host Python `chat_completion(role='FIXER')`, provider HTTP and retries/schema fallback | No per-invocation bound | Controlled GPT-4o text requests reserve from the invocation; all other live tariffs remain refused |
| Other model roles/raw judge utilities | Their existing senders and transports | Existing role holds/SAM meter, outside this fixer invocation | Not promoted to hard dollar bounds by this change |

The sandboxed Muse screenshot judge also calls the bounded wrapper and is now
refused. The raw host judge and trust-probe utilities still use soft invocation
holds; they are outside the managed fixer path and are not a paid-ceiling claim.

The original proxy allows `.meta.ai`, including subdomains, and does not constrain
HTTP method/path. With `--unshare-net` the bound proxy socket is the sandbox's only
exit; without the gateway, its network rule permits the host network. The bridge
only copies bytes; neither end meters money. Environment allowlists and the key
placeholder protect keys, not spend. The 15-minute timeout bounds runtime, not
billable requests or tokens. The source passes no verified CLI turn/token limit;
Muse Code and mitmdump are not installed here, so no claim about their available
CLI flags or real TLS integration is made.

## What is enforced, and what is a prototype

The production admission function supports only the recorded controlled
`llm-patch` tariff described above. Missing, invalid or zero invocation caps
send nothing. Muse/BYO CLI starts still stop `fixer-bound-unavailable` even
with a positive cap. No environment flag turns a fixture tariff into a live
CLI tariff. Raw FIXER sends without controlled invocation admission are refused.

The existing repair loop catches this as a budget stop, ends needs-review and
retains `fixer-invocation.json` beside its attempt. It does not verify a partial
patch or retry. The older demo loop also returns needs-review for a BudgetStop.
The parent's rejection is unchanged. A missing/corrupt budget record is itself a
named budget stop, not a claim that zero was spent.

The fixed-price **stand-in** exercises the strongest admission mechanism we can
prove with the available tools:

* The host reserves an entire invocation envelope before the first request.
  Each request reserves its known maximum charge before forwarding. Integer
  nanodollars avoid floating-point admission overshoot. Concurrent requests
  share one locked counter. No reservation is ever refunded.
* The proxy admits only the exact HTTPS host, port 443, POST and path in the
  trusted policy. Other hosts/paths/methods, CONNECT destinations, protocol
  upgrades and generic TCP passthrough are refused. Lazy upstream connection
  and disabled raw TCP are proxy settings, not suggestions to the fixer.
* The budget configuration/counter lives outside the fixer's writable mount.
  The fixture quota is enforced even if the client ignores the response and
  keeps trying. Subsequent requests receive refusal before any upstream send.
* Responses may report usage. JSON/SSE input/output token counters are diagnostic
  only: missing/error usage does not refund quota, and disconnecting a stream is
  not assumed to cancel provider billing. `admittedRequests` counts pre-send
  reservations and upper-bounds upstream sends; a failure before forwarding can
  leave a conservative extra reservation. Only a bounded usage tail is retained;
  no prompt, response text or key is written to the budget record.
* The prototype holds the full invocation cap through `spend.hold('muse', usd=F)`.
  PR #521's existing locked month ledger reserves the whole aggregate Muse
  process cap M once; all invocation holds must fit M. It therefore covers each
  invocation without double-reserving M per request. The fixture admission
  requires the model-month ledger; unreadable/invalid ledgers stop admission.
  Other roles' opt-in month accounting is unchanged. These are reservations,
  not a new claim that the whole month's provider bill is bounded.

At a fixture maximum of $0.10/request and an invocation envelope of $0.30,
three requests reach the stand-in server. Later attempts get 429 and the server
count stays three. Observed token counts do not buy another request. Alternative
routes get nothing. The record states `fixed-price-fixture`; the actual paid cost
of this test is $0. This is not a certified Muse tariff.

The stream/HTTP hooks are tested against a real local stand-in server with the
mitmproxy API substituted, not the mitmdump binary. A separate real-Bubblewrap
socket-route test skips by name where namespaces are unavailable. The local
container cannot create its uid map, so namespace enforcement was not run here.
The proxy refuses new sends at the cap; an uncooperative CLI may continue until
its existing process timeout. On return or timeout the durable budget stop wins,
so its partial patch cannot be accepted or called a failed repair.

## Why response metering is not a live dollar ceiling

A request can already incur more than the remaining budget before a usage event
arrives. Closing the client connection does not prove the provider stops charging.
A request-count cap alone leaves the price of one request unbounded. A locally
estimated token count, a requested CLI limit, or an output byte limit does not
bound hidden prompt/reasoning tokens or prove server billing behavior.

`agents/usage_report.py` records these Meta list prices from
`https://dev.meta.ai/docs/pricing-rate-limits`, read October 29, 2026:

| Unit | Recorded list price |
| --- | --- |
| SAM image | $2.50 / 1,000 images |
| SAM video | $0.20 / 1,000 frames, with the client's 50-frame minimum |
| Spark Standard input, cached | $0.15 / million tokens |
| Spark Standard input, uncached | $1.25 / million tokens |
| Spark Standard output | $4.25 / million tokens |
| Spark Contributor input, cached / uncached | $0.002 / $0.10 per million tokens |
| Spark Contributor output | $0.20 / million tokens |

That same file explicitly says the usage export does **not** identify the model or
mode Muse Code uses. A historical total matching Contributor rates does not bind
a future invocation. The JIT $1/$4 token prices are explicitly assumptions in
`expectrail/jit/run.py`, not a usable list-price guarantee. Those figures do not certify Muse pricing. The subsequent controlled llm-patch
change records its distinct OpenAI tariff with a public source.

To permit a nonzero live bound, the host needs a verified endpoint/model/mode and
complete maximum-charge rule; a provable bound on every billable input unit;
server-enforced output/reasoning limits; and any other fees/rounding included.
The host can then reserve that full worst case before a request leaves. A
provider-enforced prepaid quota/per-request authorization covering all billable
work could supply the alternative. The CLI must work through that closed route;
real TLS, streaming, redirects, errors and timeouts must be checked without
letting it open another route. None of these missing provider guarantees is
invented by the stand-in.

## Sean's end-to-end number

For **the blocked Muse CLI approved-reproduction path**, with no `--propose`,
Meta SAM image observation explicitly selected and a $2 SAM process cap:

* One intake worker admits at most 800 image attempts at the recorded $0.0025
  list price; failed/retried attempts count against the same cap. Upper bound: $2.
* The live fixer is refused before startup. It sends zero requests: $0.
* No candidate verification is started: $0. No generator is requested: $0.

The exact upper envelope from those caps alone is **$2 + $0 + $0 = $2** at the
repo's recorded SAM list price. It may cost less, including $0 with the engine-only
proof. This is a **blocked repair**, not a working live end-to-end repair quote.
For a functioning nonzero live Muse repair, **no finite certified dollar ceiling
can be quoted from the present code/provider evidence**. For arbitrary provider
choices or `--propose`, existing token/request holds likewise do not establish
that ceiling. Sean cannot use a $1 invocation hold or the $0.30 fixture tariff to
approve such a paid run.

If a real per-request maximum is later certified, with A attempts, invocation
cap F, aggregate fixer cap M and SAM cap S per fresh worker, the intended envelope
would be `min(A × F, M) + (1 + A) × S`, before stricter month admission. Today its
nonzero fixer term is unavailable; this formula is not offered as an enforced
live-Muse dollar guarantee.

For an enabled controlled llm-patch repair, use the separate [$8.75 cap-only envelope](llm-patch-spend.md).
