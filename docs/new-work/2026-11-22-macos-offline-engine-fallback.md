# Reuse the installed Mac engine when the default cache is incomplete (#249)

## What changed

Doctor and replay lookup now check that the Godot file in the default macOS
cache has execute permission before preferring it to an executable in an
older wheel. An explicitly selected engine or tools directory still takes
precedence.

## What was run

The regression ran on Linux with the Darwin lookup, a version stub in the
older installation, a mode 0644 file in the default cache and a curl stand-in.
On `df685e969b5d`, no-fetch doctor reported the engine missing, and replay
lookup called curl. After the fix, doctor ran the installed stub, replay
selected the same path and the download count was zero. The regression also
checks both explicit overrides against the incomplete cache.
[Review finding](https://github.com/Expectrail/Expectrail/pull/796#issuecomment-7084476593)

`python3 -m unittest -v tests.test_downloads.MacGodotLookup tests.test_platform_tools`
passed all 23 tests. Native macOS execution of this wheel remains open.

## Files

- `harness/run.py`
- `tests/test_downloads.py`
- `docs/install.md`
- `docs/new-work/2026-11-22-macos-offline-engine-fallback.md`
