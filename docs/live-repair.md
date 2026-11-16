# One public live-repair kit (#531)

Start with [Sean's one-page run sheet](live-repair/RUN-SHEET.md). The adjacent workflow is
only a [proposal](proposals/531-live-repair-workflow.md); nothing was dispatched.
The kit's default command is a free plan:

```sh
python3 -m tools.live_repair_kit
```

Only explicit `--run` prepares the public bug and invokes the existing CLI.
The kit fixes provider, current model, API routes, standard service tier and SAM
backend in trusted code. Report text cannot choose them or weaken policy. Muse
and BYO agent CLIs remain refused. The historical GPT-4o policy is now marked
deprecated and refused before networking; no silent fallback exists.

The OpenAI capability record now lists `gpt-6.1-sol`, its current public prices,
review date/status/expiry, output-limit field and context ceiling. Standard
$2/$10 per million is a base price, not the whole conservative reservation rule.
The model page documents long-context 2x input/1.5x output, 1.25x cache writes and
1.1x regional processing. The Chat Completions reference defaults this literal-text
request to its 30-minute cache-write tier; no 12-hour breakpoint can be selected
by the closed request shape. Its reference excerpt is included too. Reserving all these uplifts gives $5.50/$16.50 per
million. Fast/Ultrafast are excluded by explicit `service_tier=default`; no tools
are enabled. The [table/model excerpts](live-repair/price-provenance.txt) preserve the source.

The new model's framing has not been calibrated live. Its byte count is recorded,
but admission reserves the **entire published input-context maximum**, avoiding
reliance on a guessed framing margin. An oversized byte bound is refused.
Output uses `max_completion_tokens`, including reasoning. Each request maximum
is `1,050,000 × $0.0000055 + 4,096 × $0.0000165 = $5.842584` at defaults.
Retries/schema fallbacks reserve again, without refunds. With a $6 invocation cap,
a second such request is refused. The existing shared meter/role/month admission
still controls the sends. Usage violations stop for review and cannot produce
an accepted partial patch. The provider must honor its limits and billing; no
local code can prevent its own misbilling. Live availability, conformance,
quality and billed cost remain unmeasured.

Availability is separate from inference. Inactive/expired local records make no
network call. An active record requires a fail-closed model-metadata GET before
an inference POST. Metadata failure never substitutes another model. A withdrawal
between GET and POST cannot be predicted; a 404/410 at POST becomes a named stop
without retry or fallback. The metadata request is recorded in the rehearsal and
is not an inference charge. The seven-day local review must be refreshed by a
reviewed change with new source evidence, not an environment override.

## What is rehearsed

`python3 -m tools.live_repair_rehearsal --out runs/rehearsal` launches localhost
provider and SAM-wire-format vision servers, then the real subprocess command:

```sh
expectrail ingest report.json --project PROJECT --execution-class isolated --repair --repair-agent llm-patch --repair-attempts 1 --json
```

Only the HTTP socket destinations are replaced, in a trusted offline bootstrap.
Unknown destinations are refused. No replay, evaluator, reproduction check,
approved policy, fix loop, retry rule, observer-combination rule or gate decision
is substituted. Each run uses its own fresh SAM cache and forces full-frame confirmation; offline
answers cannot cross into a later live run. The existing source collector includes
project settings and the entry scene’s direct source dependencies before ancillary files, within the same
12-file/32,000-character limits, so the actual player mask and ground layer are
in the fixer request. This is context ordering, not a new fixer or check rule.
The stand-in fixer returns a saved public collision-mask repair,
a still-broken candidate, or HTTP 500 to exercise the cap before its retry.
The stand-in vision locates the robot's blue pixels in real PNGs with a narrow
fixture heuristic; it is not a live model, a general object detector, a recorded
SAM answer, or independent evidence of model quality. It never reads a trace or
verdict. Rehearsal requires Pillow, Godot, Xvfb and working Bubblewrap; tests skip
by name when their selected integration evidence is unavailable. Unit discovery
and admission tests do not require numpy or Pillow.

A real capture exposed a trace bug: `viewport` used the logical stretch rectangle
while role boxes and PNGs used physical pixels. The writer now records the window's
pixel size. The evidence validator checks it against every retained replay's PNG,
so configured engine observations can see the actual drawing. The game, existing
checks and protected verifier files were not changed.

Before any live run, the success criterion is one approved report, one candidate,
and a fresh gate acceptance with both observers, real sandboxed replays and
complete budgets. Even success would show only one public seeded case and that
model's response on that occasion. It would not establish a repair rate, robustness
on unknown games, held-out performance, broad visual correctness, or the quality
of generated checks. The rehearsal's accepted patch is scripted, so its outcome
is wiring evidence only.

The [compact final run record](live-repair/rehearsal.json) shows 37 sandboxed
Godot replays: 19 for acceptance, 11 for the rejected candidate and 7 for the
budget stop. The final fresh-cache runs used respectively 1/158, 1/16 and 1/8
fixer/vision POSTs, plus one unbilled model-metadata GET per case. Every recorded
POST reconciles to its pre-send reservation. Full traces, manifests, selected
frames and final repair-run records are in the handover’s evidence/index.html.
