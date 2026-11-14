# The edge-function test asks Node for TAP

## What changed
`tests/test_runit_edge.py` runs the edge function's JavaScript tests with `node --test` and looks for `# fail 0` in the output. Node 24 no longer prints TAP by default, so on a machine with Node 24 all 16 JavaScript tests passed and the Python test still failed (found by the ChatGPT builder on #365). The test now passes `--test-reporter=tap`, which Node has had since 18.15 and 19.6, so the output is TAP on every Node version.

## What was run
- `python3 -m unittest tests.test_runit_edge` with Node 22.23.4: OK.
- The full suite (in the PR).

## Not done
- Not run with Node 24 here. The builder that found it has Node 24.22.1 and can confirm.

## Files
- tests/test_runit_edge.py
