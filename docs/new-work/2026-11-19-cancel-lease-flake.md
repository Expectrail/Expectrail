# The cancel-then-worker test no longer races the 0.6 s lease (#649)

## What changed

Main went red at 8c2f9a2. `CancelOrderTest.test_a_worker_that_arrives_after_the_cancel_does_nothing` returned `failed` instead of `cancelled`. The cause was the test's clock, not the store. The test lease is 0.6 s. When the runner reached `cancel` more than 0.6 s after queueing the job, the store correctly saw a job that no worker took in time and failed it. That is a different path from the one this test is about.

The test now holds `expectrail.orchestrator.store.now` at the moment just before the job is queued, so cancel-then-worker is deterministic whatever the runner's speed. The store's own behaviour is unchanged, and the lease-expiry path keeps its own tests.

## What was run

- With an 0.8 s delay injected after queueing, the original test failed, reproducing the CI failure. The changed test passed.
- `python3 -m unittest tests.test_orchestrator`: OK.
- The full suite, in 3 parts: OK.

## Not done

- No other lease-timed test was audited for the same race. If another one flakes, this is the pattern to apply.

## Files

- `tests/test_orchestrator.py`
- `docs/new-work/2026-11-19-cancel-lease-flake.md`
