# Check the selected Godot project before reporting readiness (#333)

## What changed

A configured folder could lose its Godot descriptor and still receive a successful doctor report. Doctor now checks the folder before probing the machine. An explicit path to a file or a nonexistent directory gives a usage error (exit 5). A folder missing its required descriptor gives a failed readiness check (exit 3) with the file to restore. The same readiness check applies in the current directory when its project config is present.

## What was run

On the existing healthy-machine test fixture, removing only `project.godot` reproduced exit 0 and JSON `ok: true`, both with `--project` and from inside the configured directory. The new regressions passed after the fix. The doctor, recorded-renderer drift, wheel-sample and trial-stop test modules ran 83 tests, with 3 skipped. The regression also checks that an invalid project does not start an engine probe.

## Not done

A successful tag-triggered release run for #333 remains Sean’s step.

## Files

`expectrail/doctor.py`, `tests/test_doctor.py` and this entry.
