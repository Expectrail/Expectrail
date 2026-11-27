# Diagnose a missing explicit Godot executable (#333)

## What changed

When `EXPECTRAIL_GODOT` selects a missing file or a directory, doctor names
the setting and explains how to correct or unset it. The same advice applies
with and without `--no-fetch`. Automatic lookup keeps its download and
package-install advice.

## What was run

On main `35c961b2`, the Linux package job ran the installed wheel with
`EXPECTRAIL_GODOT="$RUNNER_TEMP/no-such-engine"`. Doctor exited 3 and
suggested allowing a GitHub download. The explicit setting prevents that
download. The job also ran the wheel with its usual engine and found only
the vision key and cap missing. [Installed-wheel log](https://github.com/Expectrail/Expectrail/actions/runs/45814964550/job/139892199793)

## Not done

The new regression and full discovery on the combined #333 tree still
need a Linux worker that can start processes. The historical suite result
on the published doctor branch predates this change.

## Files

- `expectrail/doctor.py`
- `tests/test_doctor.py`
- `docs/new-work/2026-11-26-doctor-engine-path-fix.md`
