# Keep the installed sample judging captured observations (#257, PR #589)

## What changed

The new capture path emitted observations/v1, whose runtime validator imported the optional
`jsonschema` package. A normal wheel has no dependencies. Its evaluator stopped with
ModuleNotFoundError, so even the seeded fall-through bug became needs-review. No module or
schema was missing from the wheel. The timeline reader now uses the gate's existing strict
standard-library schema validator on the same observations schema, before reading identity
fields. It still checks provenance, completeness, identity and geometry. No format, approval,
packaging allowlist or gate decision rule changes.

Package tests now pip-install the built wheel, offline, into an empty temporary venv and
exercise its console script outside the checkout. A replay stand-in covers all three sample
cases and runs the unchanged `tools/check_no_vision.py`; a second test runs the real command
with Godot and required sandboxing where available. A dependency-free reader test refuses
seven missing provenance/geometry fields. All 92 existing assertion calls remain unchanged.

## What was run

- Required historic fetch, and PR head `2c5d59fd31c5917f4a47e265a6361664dfe7b1bb` fetched.
- Public CI package job 133832482888 and quickstart-timing job 133832482420, run
  [44021713923](https://github.com/Expectrail/Expectrail/actions/runs/44021713923), inspected.
  Its quickstart artifact shows all three sample decisions were needs-review.
- Two new installed-wheel tests failed on the old code: sample decisions differed and
  the timeline reader could not import jsonschema. The final stand-in also fails the old
  wheel at the guard's exact `check_no_vision.py` line 18. The fixed wheel passes it.
- Focused package and timeline suite: 46 tests, 0 failures/errors, 2 named prerequisite skips.
- Real installed-wheel sample with Godot 4.7.2 and a local virtual display, no keys, no cap:
  before: needs-review / needs-review / needs-review; all engine checks stopped on the missing
  jsonschema import. After: needs-review / reject / needs-review. The engine passes clean and
  repaired, and rejects the broken copy at frame 5 (22.25 px beyond the boundary).
  Exit code 3 on both invocations. Sandbox was explicitly off: this machine refuses Bubblewrap
  namespaces. This is real replay evidence, **not proof of sandbox isolation**.
- Discovery with NumPy and Pillow blocked: 4,781 tests loaded, 0 import errors.
- Full suite before: 4,676 tests in 543.183s; 0 failures, 0 errors, 61 skips. After: 4,679 tests in 530.597s; 0 failures, 0 errors, 62 skips. Failing test names: none in either run. The one additional skip is the newly added native installed-sample test; it requires Godot and sandboxing.
- Export scan: 836 files, 0 errors, 0 warnings. `git diff --check` passed.

## Not done

No live model call, spend, workflow dispatch, GitHub write or push. A real sandbox-required
installed sample must still run on CI; the local test names the unavailable Bubblewrap sandbox.
The offline stand-in's isolation record is synthetic and is not claimed as real isolation.
The episode interpreter's fractional clock remains the separate next slice, after this PR merges.
This patch applies to #589's exact head as requested. A merge preview with main
`49226b6cdadda80754ecee1c61ed33116aeb9b6c` was clean; its merged full suite was not run.

## Files

- `expectrail/observation_timeline.py`
- `tests/test_package.py`
- `tests/fixtures/installed_sample.py`
- `docs/new-work/2026-11-17-installed-timeline.md`
