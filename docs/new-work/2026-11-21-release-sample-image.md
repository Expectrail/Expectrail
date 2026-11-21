# Build and check the recorded-sample image in the release workflow (#249)

## What changed

The release job builds the existing Linux amd64 recorded-sample container from its wheel and
the SHA-512-verified public Godot archive from the shared download action. It runs installed doctor and the clean, broken and
repaired Godot sample cases by image ID with networking disabled. The run summary records the
local image ID after the smoke check succeeds.

## What was run

- `python3 -m unittest tests.test_release_workflow tests.test_downloads` passed all 22 tests.
  The new regression failed on the original workflow because the image build step was absent.

- On November 21, 2026, built the wheel, verified the cached Godot archive and ran the workflow's image
  build and smoke scripts locally on main `d5b1e8f` with this change. Doctor exited 0 and the three
  completed Godot cases returned accept, reject and accept
  using saved vision, with networking disabled. Local image ID:
  `sha256:0f0184b1c9f34f5f8f5a4954833e57cb11475c8657eba2dce55d03667dcef9ff`.
- `actionlint .github/workflows/release.yml` passed. A stand-in sample exit of 5 stopped the smoke
  step and printed its output.

- `python3 -m unittest discover -s tests -t .` on `d5b1e8f` with the corrected workflow passed
  5,950 tests with 223 skipped in a clean virtual environment with Node.js and required package
  and gateway tests.
- After updating to `c369b5d`, which added only three documentation changes, the release,
  download and capability tests passed all 71 tests. The export scan covered 1,332 files with
  zero errors and zero warnings.

## Not done

The GitHub release workflow has yet to run with this change. The release tag and any registry
publication require Sean.

## Files

- `.github/workflows/release.yml`
- `tests/test_release_workflow.py`
- `docs/install.md`
