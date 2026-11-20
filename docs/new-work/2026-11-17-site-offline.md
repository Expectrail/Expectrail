# Earlier evidence during an outage, local Worker quotas and receipt files (#265)

## What changed

The existing Run it page loads a committed earlier-results index independently of the
Worker and remote results. A static section also works without JavaScript. The three
saved results are the public November 13 recordings, copied byte for byte from
`Expectrail/Expectrail` ref `3adf65eca0883c0af97ff9e4c526f815a21a1c15`:

| Sample | Finished (UTC, November 13) | Recorded result | Vision answers |
| --- | --- | --- | --- |
| Clean | 21:50:35 | accept | 120/120 |
| Fall-through bug | 21:54:50 | reject | 135/135 |
| Repair | 21:53:05 | accept | 135/135 |

`docs/run-it/earlier/source.json` records the pinned ref, each original Git blob ID,
SHA-256 and byte length. These are earlier published results, not runs performed by
this change. Findings and status are validated together before showing a cached
verdict; inconsistent counts or observer outcomes fail closed. The page labels saved
results as earlier, gives their dates and shows their real check rows. Full frames
are not cached; their original viewer is linked separately. Request timeouts now
cover the body as well as headers. Selecting another case prevents stale responses
from replacing its result. The site index links the earlier evidence.

The receipt widget uses the existing #255 `expectrail.receipt/v1` reader, with a
visitor-selected receipt, trust store and independently supplied expected digests.
It sends no file to a server. Its default is **receipt not yet available**. Clearance
applies only to the selected file and never becomes a receipt for the unsigned saved
run. Missing/unknown trust, changed expectations, tampering, expiry and the legacy
format cannot produce clearance. Changing the case/files clears the displayed check.

`node apps/run-it-edge/burst.mjs` imports the actual Worker adapter and service. It
supplies local Durable Object storage, a clock and strict fake GitHub transport; it
does not exercise the Python stub or make a real dispatch. Admission limits are the
unchanged production defaults. The measured primary waves were:

| Scope | Requests | Accepted | Busy | Refused by limit |
| --- | ---: | ---: | ---: | ---: |
| Same visitor | 800 | 3 | 597 | 200 visitor quota |
| Daily, distinct visitors | 1,200 | 40 | 960 | 200 daily cap |
| Three consecutive failed runs | 800 | 3 | 597 | 200 circuit open |

Four additional POST controls prove the two midnight resets, persistence of the
breaker across midnight, and its explicit epoch reset: **2,804 POSTs total**.
Restarts retain visitor/daily/breaker state. The transport handled 49 fake dispatches
and 195 fake calls, **zero real external requests**. Raw visitor addresses were not
stored. This proves code admission with scripted storage/clock/platform headers;
it does not establish deployed Cloudflare behavior or play/verify a game.

## What was run

Base: `97f34660eb0a10ba242acc3ac9a6a194ab2eb0c4`, fetched from main at task start.
Read AGENTS.md first and completed the required historic
`c169a5e0da304773587304ed47bc8aabcec80da7` fetch. Work is on
`chatgpt/265-site-offline`. The user explicitly authorized editing the existing
`docs/run-it/` page.

- Full unmodified before: `python3 -m unittest discover -s tests -t .`, with all
  `EXPECTRAIL_*` variables unset: **4,696 tests, 757.152s, one failure, 60 skips**.
  The sole failure was
  `tests.test_orchestrator.ProcessTest.test_waiting_on_a_worker_that_died_reports_it_at_once`:
  0.7547s included descendant cleanup. Task 1's separate preceding #365 patch fixes
  the test's recognition/cleanup timing distinction and retains its assertion.
- Local Worker burst: table above; summary JSON included in handover.
- `python3 -m unittest -v tests.test_runit_offline`: **9 tests, 24.061s, OK**, using
  real Playwright Chromium. Disabled/unreachable Workers, a hanging response body,
  desktop/phone layout, all three cached verdicts, JavaScript disabled, inconsistent
  cached counts/observations, and real #255 browser file checks were exercised.
  Every browser request was restricted to loopback; attempted external requests and
  POSTs are asserted absent. Missing Chromium/Node/cryptography skips name the missing
  requirement; the existing required-web mode fails for missing Chromium.
- `python3 -m tools.runit_smoke --stand-in`: **3 stand-in runs, 9/9 checks held,
  zero problems, 33.1s**. This regression run does not play a real game.
- Initial new browser tests failed on CSS-uppercase text and Playwright string
  evaluation blocked by the existing CSP. Tests now compare source text and pass
  function predicates; the CSP and verdict assertions were preserved. Earlier
  focused development caught an unguarded browser global in the Node page fixture
  and correctly rejected an empty trust store as invalid. Both were corrected.
- First ordered full after: **4,733 tests, 883.503s, one error, 53 skips**.
  `tests.test_visible_repair.RepairTest.test_unpublished_card_is_disabled_and_ignores_an_old_latest_run`
  failed because its Node fixture's exact request inventory did not include the new
  earlier index. The fixture now supplies both indexes, with valid dates and old
  unpublished-fix entries. Its exact request equality and all disabled/hidden
  assertions are retained, additionally proving neither old result is fetched.

Guard: test change intended (#265)

- Ordered-bundle full after: 4,733 tests, 962.205s; OK (skipped=53). No failures or errors. Node suite: 25/25 passed (1.926s). Two test modules (19 tests) load with numpy/PIL blocked; the four new core tests also pass with both blocked (0.968s). Site/link tests: 8/8 passed. Public export: 843 files, 13 prohibited paths excluded by metadata, zero errors/warnings. Final patch application and whitespace checks passed.

The final suite validates the **ordered bundle**: this latest-main base plus the
preceding Task 1/2 patch and this Task 3 patch, in a separate integration checkout.
The Task 3 patch itself includes no packaging or #365 test changes. Test logs name
every failure and its cause. No existing test is loosened.

## Not done

No deployment, call to the deployed API, real dispatch, model call/spend, new game
verification, GitHub write, push or PR. No production receipt, issuer key or trust
store was manufactured. The merged Run it result contract still says unsigned;
automatic signed-result publication needs its own contract/writer integration.
No claim that #265's deployed/end-to-end Done cases are complete. Saved full frames
remain online-only; the local fallback preserves findings/status and provenance.
No workflow, approval, game source or protected verifier/orchestrator code changed.
No private, blind or fresh content read. Public export scanning excludes prohibited
paths by metadata before opening; this limitation is recorded in the handover log.

## Files

- `apps/run-it-edge/burst.mjs`, `package.json`, `test/burst.test.mjs`
- `docs/index.html`, `docs/run-it/index.html`, `run-it.js`, `receipt-panel.js`
- `docs/run-it/earlier/`: index, three status/findings pairs and source inventory
- `tests/test_runit_offline.py`
- `tests/runit_repair_card.cjs`
- `docs/new-work/2026-11-17-site-offline.md`
