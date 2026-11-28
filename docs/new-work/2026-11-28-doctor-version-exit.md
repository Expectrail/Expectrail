# Report a failed Godot version command (#333)

## What changed

The Godot check in `expectrail doctor` now requires the version command to exit successfully before using the version it printed. If it fails, the diagnostic reports the exit code, gives the existing engine replacement advice and skips the drawing probe. Both normal lookup and `--no-fetch` use this check. The engine preflight calls the same function.

## What was run

The new CLI regression uses an executable that prints the pinned Godot version, writes a diagnostic to stderr and exits 7 on `--version`. It would otherwise report a working renderer. In each lookup mode the test requires exit 3, a valid doctor JSON document, the failed version check, a skipped drawing probe and no subprocess diagnostic in the output.

On published commit `2f1e3300`, the independent Linux run reproduced doctor exit 0 in both modes despite Godot exiting 7. On tree `9929bbef`, the focused CLI regression passed and real Godot 4.7.2 drew a frame under Xvfb in 26.739 seconds. Full discovery ran 6,114 tests with 57 skips. Its only failure was the heading on this entry. The reviewer corrected the heading in their checkout and both work-log tests passed. [Independent run](https://github.com/Expectrail/Expectrail/issues/333#issuecomment-7234097444)

## Not done

Full Linux discovery on this corrected log is pending. The final result belongs on [issue #333](https://github.com/Expectrail/Expectrail/issues/333).

## Files

- `expectrail/doctor.py`
- `tests/test_doctor.py`
- `docs/new-work/2026-11-28-doctor-version-exit.md`
