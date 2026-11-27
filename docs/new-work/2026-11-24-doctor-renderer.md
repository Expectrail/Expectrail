# Identify the renderer used for the bundled sample (#333)

## What changed

When Godot drew a frame using Mesa softpipe, `expectrail doctor` named the
device and then said it was outside Mesa's software renderers. Softpipe and
llvmpipe are both software renderers. Doctor now reports the device Godot
used, names llvmpipe as the renderer on which the bundled sample has been
verified, and explains that captured images can differ on another device.
A successful draw still passes the OpenGL check.
[Mesa's software renderer selection](https://docs.mesa3d.org/envvars.html#envvar-GALLIUM_DRIVER)

## What was run

On Debian 13 with Python 3.12.14, I installed the release rehearsal wheel in
an empty venv with only loopback networking. Its SHA-256 matched the artifact's
checksum, `b85e0daa51b00944827656bd132eee5a2766bfcc6f597eb3c80b501555994867`.
Godot 4.7.2 drew a frame with each of Mesa llvmpipe and Mesa softpipe.
Doctor exited 0 for both in the recorded-sample profile. Making only
`patch` unavailable gave exit 3 and the fix `sudo apt-get install patch`.
A verify request missing its required head gave exit 5 and created zero jobs.
[Release rehearsal](https://github.com/Expectrail/Expectrail/actions/runs/44983211397)

The same installed wheel on Mesa llvmpipe (LLVM 19.1.7) accepted the clean
sample, rejected the fall-through copy and accepted the repair using recorded
vision. The five Godot replay logs each named the same device that doctor
reported. The jobs were `0351cb7016c751d77973db01be996ac6`, `f5d2b6789d31fa675eafbf836f1a1ef2` and `b7f2b016d824222ac922fc894c672650`, respectively.

With the changed wheel, the installed doctor named softpipe and explained the
llvmpipe comparison. The llvmpipe and missing-tool controls returned the same
results as before. No model credentials were present.

Two device cases failed on the previous branch head. With the change,
`python3 -m unittest -v tests.test_doctor tests.test_wheel_sample` ran 46
tests with one skip and zero failures. The new regression also passed in a
venv without NumPy or Pillow.

## Not done

The release workflow has a successful manual rehearsal. A tag-triggered build
still needs Sean. The sandbox's display probe has a separate open finding.
[Display probe reproduction](https://github.com/Expectrail/Expectrail/issues/333#issuecomment-7116103574)

## Files

- `expectrail/doctor.py`
- `tests/test_doctor.py`
- `docs/new-work/2026-11-24-doctor-renderer.md`
