# Keep the caller's relative Godot executable through doctor and verify (#333)

## What changed

An explicit `EXPECTRAIL_GODOT` path is anchored in the caller's directory.
This lets doctor start a binary named `./selected engine` and lets the
verification worker use the same binary after it changes directory. The
worker sets the absolute path in its own environment.

## What was run

On Linux at `de1ddd65`, the same pinned Godot executable passed the version
probe by absolute path and returned `FileNotFoundError` by relative path.
Both fetch modes showed the difference. The worker regression also failed
when the engine was present under the caller's directory.

After the change, `python3 -m unittest -v tests.test_doctor tests.test_downloads`
ran 57 tests, with one optional test skipped. The new cases passed.

A wheel built and installed offline had SHA-256
`8928d8cd2d4cd9c17a2a59b79ac2a1b4266413d41afd306443243d8c1fd0ac2b`.
Outside the source tree, `EXPECTRAIL_GODOT="./selected engine"` pointed to
Godot 4.7.2. In the bundled recorded-sample profile, doctor and doctor
with `--no-fetch` both exited 0. Both checked the engine, OpenGL and the
sample recordings. With the profile removed, a normal verify job compared
the clean bundled game with its seeded fall-through copy. It completed
with exit 1 and reject. One public check failed after the change.

## Not done

The Linux verification ran without vision credentials. Native macOS and the
release-tag rehearsal were outside this run.

## Files

- `harness/run.py`
- `expectrail/orchestrator/runner.py`
- `tests/test_doctor.py`
- `docs/new-work/2026-11-23-doctor-engine-override.md`
