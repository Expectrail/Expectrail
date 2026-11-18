# Status deadlines and the native Worker test lane (#265)

The November 17 open check found a healthy run whose status request outlasted the
smoke client's ten-second poll. A refresh could serially read the run list, run,
jobs and sometimes published phase, each with a separate ten-second deadline.
The initial deployment also rejected `redirect: "error"` before sending a dispatch;
#595's `manual` mode remains in place.

## The status answer and refresh

| Boundary | Current rule |
| --- | --- |
| Status answer | Read saved state, wait at most **250 ms** for freshness, then answer with the last known state and its existing `updatedAt`. |
| Upstream refresh | **2 seconds total** across run-list, run, jobs and published-phase reads, including JSON bodies; one shared abort signal. |
| Concurrent polls | Share one refresh per request id; reuse completed or timed-out attempts for **10 seconds**. |
| Smoke status request | **5-second socket timeout**, clipped to remaining `--wait`; allows transport and scheduling margin. No start/dispatch retry. |

These are application deadlines. Platform storage, CPU scheduling and network
transit are outside a hard wall-clock SLA. Status reads do not enter the admission
queue. Upstream work runs outside its lock; only the resulting state mutation is
serialized. `RunIt` registers the refresh with Durable Object `waitUntil`, so the
short answer does not abandon it. A confirmed run id survives a later jobs timeout.

An unreadable or expired read keeps the last state, reservation and breaker count.
Late responses cannot resume a cancelled sequence or overwrite a newer state.
Busy means the prior request is reserved or running; it does not promise GitHub
has started it. The existing five-minute lost-run policy needs a successful empty
list; the thirty-minute tracking policy now also needs a successful observation.
Age during an outage cannot manufacture failure or free another dispatch.
Confirmed workflow failures still fail and count toward the breaker. An unreadable
published phase neither counts nor resets it.

The `expectrail.run-it-api/v1` response shape is unchanged. Progress comes from
this API; published findings supply the verdict.

## Install and run the pinned runtime locally

Production has no npm dependencies. The optional dependency and full integrity lock
are in `apps/run-it-edge/runtime/`. Install outside the source checkout so vendor
files do not become part of source/export scans:

```sh
RUNTIME_DIR="$(mktemp -d)"
cp apps/run-it-edge/runtime/package.json apps/run-it-edge/runtime/package-lock.json "$RUNTIME_DIR/"
npm ci --prefix "$RUNTIME_DIR" --ignore-scripts --no-audit --no-fund
NODE_PATH="$RUNTIME_DIR/node_modules" node apps/run-it-edge/test/runtime-check.mjs
NODE_PATH="$RUNTIME_DIR/node_modules" EXPECTRAIL_WORKER_TESTS=required python3 -m unittest -v tests.test_runit_status_bound
```

Pins: **Miniflare 4.20260730.0**, locked **workerd 1.20260730.1**, Node 22 or newer.
The recorded executable says `workerd 2026-07-30`. Tests use compatibility date
**2026-07-30**, supported by that pinned engine. The production example requests
**2026-11-01**; this lane does not validate that later compatibility set or the
deployed engine version. Upgrading the pin needs its own reviewed run.

When the package is absent, Python and Node cases skip by name and say which
runtime is missing. `EXPECTRAIL_WORKER_TESTS=required` makes a missing prerequisite
fail. Wrong installed versions and runtime crashes fail. Discovery never installs
packages or deploys. Dependency-free tests are `npm --prefix apps/run-it-edge test`;
native cases alone are `npm --prefix apps/run-it-edge run test:runtime` with the
same `NODE_PATH`.

## What the native lane runs

Miniflare runs the actual `worker.js`, `RunIt` SQLite Durable Object and `service.js`
inside workerd, with no replacement service or patched clock. Its outbound service
intercepts every fetch and implements allowlisted fake GitHub endpoints. An
unexpected destination fails. There is no real token, account, dispatch, game or model.

1. A native dispatch reaches fake GitHub once; queued, running, publishing and
   published phases follow through real DO storage.
2. Thirty simultaneous polls return cached answers within the test's 1.2-second
   scheduling envelope while three 800-ms reads share the two-second deadline.
   One refresh starts; the reservation remains and a later poll recovers.
3. Headers followed by incomplete JSON expire too. Late failure bytes do not
   replace saved state or permit another dispatch.
4. An actual redirect response is refused without following its destination.
5. A mutation back to `redirect: "error"` is caught by the same dispatch assertion:
   workerd throws before fake GitHub is called. Node alone accepts that option.

The final native run passed **5 tests in 67.775s**, zero skips, with **zero host
non-loopback HTTP attempts**. Miniflare metadata fetching is explicitly disabled
(`cf: false`); a host dispatcher guard counts and blocks non-loopback HTTP while
preserving its existing connection pools. Worker outbound calls all use fake
GitHub. The final native response bodies passed the merged API reader. Existing service
cases plus six new deadline cases passed **31 tests in 6.587s**. The smoke plus its
two new timeout cases passed **16 tests in 1.520s**. New bodies also pass the merged
API reader through `tests/test_runit_status_bound.py`; its recorded run is retained
in the handover. These are local API/runtime measurements with fake GitHub. They
do not measure a game verdict. Full suite results and baseline failures are in the
work log and handover logs.

Sean's dedicated job is proposed in
[`proposals/265-workerd-runtime.yml.txt`](proposals/265-workerd-runtime.yml.txt).
It requires the runtime and uploads its log. Hosted CI and deployment of this
status/runtime change have not run here.
