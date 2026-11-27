# Preserve the preflight diagnostic for a missing Godot override (#333)

## What changed

When an explicit Godot path is missing, verification preflight and the default
`doctor` command keep their established FileNotFoundError message. The remedy
tells the developer to correct or unset `EXPECTRAIL_GODOT`. In no-fetch mode,
doctor identifies the invalid override directly. The regression checks the
message and remedy for a missing file and a directory in both modes.

## What was run

On the preceding tree `d2d9ae52`, builder two ran 6,113 Linux tests with
57 skips. One failed. The preflight regression reproduced in isolation because
the diagnostic prefix changed. The two focused doctor checks, a Godot 4.7.2
frame under Xvfb, and the export scan over 1,402 files passed on that tree.
[Independent verification](https://github.com/Expectrail/Expectrail/issues/333#issuecomment-7212068612)

## Not done

The corrected tree still needs the focused checks and full Linux discovery.

## Files

- `expectrail/doctor.py`
- `tests/test_doctor.py`
- `docs/new-work/2026-11-27-doctor-preflight-override.md`
