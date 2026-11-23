# Exercise the fixer cap assertions on Linux with Bubblewrap (#267)

## What changed

The fixer cap test now reads the exit status from the process returned by
`run_sandboxed`. Unpacking that object as a pair raised a `TypeError`
before the test could check the process status and the upstream request count.
This surfaced during full discovery for the local app on a Linux host where
Bubblewrap could create its sandbox.

## What was run

Before the correction, the real Bubblewrap case raised
`TypeError: cannot unpack non-iterable CompletedProcess object`.
After the correction, `python3 -m unittest -v tests.test_fixer_invocation_cap`
ran all 23 tests successfully, including the real Bubblewrap case. The
fixture uses a local HTTP server. The test checks that three requests reach
it, the next request is capped, and an unlisted path is refused.

## Not done

The run used no live fixer or model.

## Files

- `tests/test_fixer_invocation_cap.py`
- `docs/new-work/2026-11-23-fixer-sandbox-result.md`
