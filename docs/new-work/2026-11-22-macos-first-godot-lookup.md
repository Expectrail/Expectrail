# Return the installed Godot path on the first macOS lookup (#333)

## What changed

Doctor and replay read the last line of the macOS download helper's standard output as the executable path. A fresh install put a readiness message on that line, so doctor could report Godot missing immediately after extraction. The helper now prints the message to standard error and the executable path on the last line of standard output.

## What was run

On November 22, `python3 -m unittest -v tests.test_downloads.MacGodotLookup` failed on main with `FileNotFoundError` in the Godot check even though the fixture executable existed. It passed after the change. The test uses macOS platform selection, an empty engine folder, a small ZIP, and a stand-in for curl. Bash runs the helper, including its checksum and extraction commands. The first and cached lookups returned the same exact path, including spaces. The download stand-in was called once.

The downloader and doctor test modules passed together with 49 tests run and one skip. An offline wheel rehearsal in a clean virtual environment on Linux also exercised the installed helper with a fixture archive and its checksum. Doctor reported `ok` on both lookups.

## Not done

A cold install of the real Godot release on a macOS machine remains unmeasured. The tagged release trial is Sean's step.

## Files

- `harness/macos/get_godot_mac.sh`
- `tests/test_downloads.py`
- `docs/new-work/2026-11-22-macos-first-godot-lookup.md`
