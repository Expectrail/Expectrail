# Add the public release evaluation registration (#742)

## What changed

The versioned registration records the seven questions and the fixed measurement rules from #282.
It gives Sean explicit fields for the run window, thresholds, caps, pins and sign-off. The checkout
reader validates drafts and complete registrations. The writer makes a canonical copy at a new path.
The checked-in example is a synthetic draft with human decisions left empty.

## What was run

The registration tests first failed because the v2 reader did not exist. The focused tests use
synthetic registrations and check that incomplete records, unintended protocol changes and the old
format fail validation. A test compares the registered minima and vocabulary with the existing
manifest validator.

- 78 focused registration, schema, manifest, package contents, link and work log tests passed.
- The checkout command accepted the draft, produced identical canonical copies, refused a write
  over an existing file and refused the draft when the reader required a registered record.
- The first full run was interrupted during HTTP server teardown. A focused run on unchanged main
  completed 64 tests with four skipped. The full rerun using
  `python3 -m unittest discover -s tests -t . -v` completed 5,997 tests with 81 skipped and zero failures.

## Not done

The manifest validator currently uses its existing minima. Connecting a real registration to that
validator or a runner, pinning actual files, setting thresholds or caps, signing and dispatching
remain separate work.

## Files

- `contracts/blind-registration.v2.schema.json` and `contracts/examples/blind-registration.v2.json`
- `expectrail/jit/registration.py` and `tests/test_jit_registration.py`
- `docs/contracts.md`
