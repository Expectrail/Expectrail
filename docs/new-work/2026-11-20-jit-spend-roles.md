# jit.yml's propose, revise and pixel-ask send only the role whose cap they set (#267)

## What changed
The spend-cap audit (`tools/spend_cap_audit.py`) follows imports. So it listed three `jit.yml` steps as
possibly reaching a sender whose cap the step does not set:

- `propose` and `revise` set only the spec cap. `expectrail.jit.cli` imports SAM's sender through
  `expectrail.jit.sam_observer`.
- `pixel-ask` exports only SAM's cap. `expectrail.jit.cli` imports a spec sender through `expectrail.jit.intent`.

All three were `unreviewed` in `tools/spend_cap_gaps.json`. They are now reviewed by running the code,
not only by reading it. The new `tests/test_jit_spend_roles.py` runs each subcommand through `cli.main`
as the step runs it:

- `urllib.request.urlopen`, the network floor of both senders, is replaced by a recorder that answers as
  the service would.
- The environment holds a made-up key and exactly the caps the step sets. A test reads those caps from
  `jit.yml` itself, so the test fails first if the workflow changes them.

Results:

- `propose`, under every offer and for both pixel observers (with the candidate withheld too): one spec
  request, no SAM request and no SAM try.
- `revise` under the pixel setting: one spec request, no SAM request.
- `pixel-ask --sam-live`: 117 images to SAM (13 a replay, nine replays), no spec request and no spec hold.
- Two controls: without its cap, each step sends nothing.

The three entries now say `not sent:` with the reason and the test. No workflow changed. `pixel-ask`'s
`cannotTell` line stays: it is the audit's own limit, since it does not follow the order of a script's
commands.

## What was run
- `python3 -m unittest tests.test_jit_spend_roles`: 8 tests, OK.
- Two mutations of `expectrail/jit/cli.py`, made and then reverted:
  - a SAM try added to `propose`: 6 failures (every offer, and the observer test);
  - a spec send added to `pixel-ask`: 1 failure.
- `python3 -m tools.spend_cap_audit --check`: exit 0.
- Full suite on main 0a96973 plus this change, without the engine: 5,480 tests, OK, 73 skipped. A first run
  errored in the two `pixel-ask` tests: `tests.test_jit_pixel_jobs` deletes its capture folder in
  `tearDownModule` and keeps its cache. The class now keeps its own; `tests.test_jit_pixel_jobs` then
  `tests.test_jit_spend_roles`, run in that order: 26 tests, OK.

Nothing was dispatched and no model was called.

## Not done
- The other 44 `unreviewed` steps in `tools/spend_cap_gaps.json`. They belong to other workflows'
  owners. Vision's caps belong to #327.
- `jit-blind.yml`'s entry. That workflow is the blind test's, so it is left alone.
- #267's live schema, error and timeout checks, and the comparison with a bill (`needs-sean`).

## Files
- `tests/test_jit_spend_roles.py` (new)
- `tools/spend_cap_gaps.json` (three entries reviewed)
- `docs/new-work/2026-11-20-jit-spend-roles.md` (this file)
