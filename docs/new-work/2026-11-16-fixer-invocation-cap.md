# Refuse unpriced live fixers; prove host admission with a stand-in (#267)

## What changed

Applied the under-review round-four handover on current main, which already
contains rounds one through three. Audited native/BYO fixer, raw judge/probe,
launcher, bridge, proxy and direct provider send paths. The audit and list-price
sources are in `docs/fixer-spend.md`.

No verified nonzero Muse dollar ceiling is established: the repo's usage export
does not identify Muse Code's model/mode, and no verified maximum billable input,
output/reasoning charge or CLI/server limit is available. Live fixer entry points
therefore require `EXPECTRAIL_FIXER_INVOCATION_USD_CAP` and stop before sending,
with `fixer-bound-unavailable` for a positive cap. Zero/missing/invalid caps stop
by name. BYO helpers and the actual default FIXER HTTP sender cannot bypass this
refusal. Offline fixture patches remain available. The sandboxed Muse judge also
uses the bounded wrapper and is refused; legacy raw host judges/probes retain
soft holds and are not a hard-dollar claim.

Implemented host-side pre-send admission in the existing gateway for a fixed-price
stand-in. A full invocation hold uses existing `spend.hold` and PR #521's locked
month admission. Each request reserves a maximum charge in integer nanodollars
before forwarding; concurrent requests cannot reuse credit. Exact host/port/
method/path, CONNECT and raw-TCP controls close alternative routes. Response token
usage is diagnostic and never refunds credit. No fixture tariff can enable a live
run through an environment switch.

Added `fixer-invocation/v1` under contracts with its example, writer and strict
reader, and a repair-run example/optional link and named stop field. The shipped
repair loop preserves the budget record, ends needs-review and neither verifies
a partial patch nor retries. The older demo loop also treats BudgetStop as review.
Updated user guides/ledger limits to state that live repair is blocked, rather
than advertise an unproved ceiling.

## What was run

Before edits, all EXPECTRAIL_* variables removed:
`python3 -m unittest discover -s tests -t .`: 4,269 tests in 367.179 seconds,
OK, 50 skipped, exit 0. Failing test names: none.

Read issue #267 and PR #521. Read agents/fixer.py, sandbox.py, gateway.py,
gateway_bridge.py, muse_gateway_addon.py, BYO/provider sender paths, spend.py and
usage_report.py. `muse` and `mitmdump` are not installed; neither was installed or
invoked, so no CLI-limit or real TLS/proxy integration claim is made.

Final focused tests: 109 tests, OK, one named Bubblewrap skip (12.386 seconds).
A real local stand-in HTTP server received exactly three admitted requests for
the synthetic $0.30 / $0.10-per-request fixture; five later requests got 429,
alternative routes got 403, and upstream count stayed three. Retained counters
show 21 observed input tokens and nine output tokens, with no credit refunded.
Concurrent admission, SSE, invalid counters/ledgers, month/aggregate holds,
pre-start live refusal, direct sender/BYO refusal, timeout-to-budget-stop and
both repair-loop stop paths were tested. The handover includes a separately
recorded stand-in run and its invocation/month records; actual paid cost was $0.

With numpy/PIL discovery and imports blocked on the final source: 89 tests, OK,
one named Bubblewrap skip (12.669 seconds). Capability render/check exited 0. The real namespace test
skipped because Bubblewrap cannot create its namespace in this container. Proxy
HTTP hooks used a mitmproxy-API stand-in, not a real TLS interception process.

Initial focused failures are retained in the handover: five old BYO metadata/wiring
unit tests needed the new admission boundary mocked because their process
transport is already a stand-in; original assertions were retained. New direct
live-refusal tests cover that boundary separately. A test-only header mapping
was case-sensitive, the new path regex needed its required sample, and the demo
loop regression omitted its required run_trust argument; those setups were
corrected, with no cap/check assertion loosened.

The first full after-suite ran 4,294 tests and found two further offline wiring
fixtures needing the admission stub:
`tests.test_byo_wiring.FixerTest.test_cli_agent_runs_in_the_workspace_with_only_its_key`
and `tests.test_byo_wiring.FixerTest.test_llm_patch_agent_produces_a_checked_candidate`.
Their assertions were retained; 75 wiring/admission/schema tests then passed.
A subsequent full run was interrupted after 151.466 seconds for a review finding:
a timeout after exactly filling the cap (without an extra refused request) must
also stop as budget, before any partial candidate can be verified. The exact-cap
and overrun timeout cases now pass; the host also rejects a different invocation
identity/cap in an otherwise valid counter. The interrupted run is not counted
as a completed suite.

Final full suite, all EXPECTRAIL_* variables removed:
`python3 -m unittest discover -s tests -t .`: 4,295 tests in 419.231 seconds,
OK, 54 skipped, exit 0. Failing test names: none. Combined/split patch
reconstruction and protected-path/approval-value audits passed.

## Not done

No live model/CLI/API call, bill measurement, production tariff certification,
actual mitmdump/TLS/CLI-limit test, or successful local Bubblewrap run. No finite
nonzero live-Muse dollar guarantee is offered. The stand-in demonstrates admission
with a known synthetic maximum, not Muse pricing. Sean's current cap-only example
is $2 for a selected SAM-only, no-proposal intake whose live fixer is refused;
it is not a quote for a functioning live repair. Provider/model/billable-unit
limits or a provider-enforced prepaid authorization are needed before enabling
one. No workflow, protected verifier, game source or approval changed; no private
or blind material read. No push, PR or GitHub write.

## Files

`agents/fixer_meter.py`, `expectrail/fixer_budget.py`, the new invocation schema
and example, repair-run schema/example, contracts registry, packaging list;
`agents/sandbox.py`, `agents/gateway.py`, `agents/muse_gateway_addon.py`,
`agents/byo_fixer.py`, `expectrail/providers.py`, both existing repair loops;
`tests/test_fixer_invocation_cap.py`, the five BYO metadata/wiring admission mocks and
schema-pattern sample; `docs/fixer-spend.md`, repair/playtest guides, capability
limits/generated page, and this log. The combined patch also contains the
separately identified round-four dependency and its original work log.
