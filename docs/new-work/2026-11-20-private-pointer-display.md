# Isolate Linux pointer captures from the desktop mouse (#733)

## What changed

When a rendered Godot route contains a pointer event and the Linux replay runs outside Bubblewrap, Expectrail starts its existing private Xvfb display and selects Godot’s X11 driver. The capture process drops the desktop X11 credentials and Wayland socket settings. This includes the runtime directory where Wayland can find its default socket.

Before importing the project, the harness uses the same virtual-display check as `expectrail doctor`. A missing component stops the capture and names the package to install. The replay’s isolation record still describes the actual sandbox mode.

## What was run

- In six real Godot 4.7.2 captures, the public Breakout route ran with a quiet desktop, desktop pointer movement, then a quiet desktop again on each harness. On main the mouse moved the paddle from x=310.000 to x=141.463 at frame 76 and the ball missed. With private X11, all three traces and all three 100-frame sequences matched the original quiet run byte for byte. The corrected paddle stayed at x=310.000 and the ball rebounded. The experiment used Xorg and llvmpipe. Bubblewrap could not set its uid map. [Replays and measurements](https://github.com/Expectrail/Expectrail/issues/733#issuecomment-7052402913)

- `python3 -m unittest -v tests.test_linux_pointer_display` exercised the replay entry point with a stand-in engine. Before the fix, the X11 desktop case launched Godot directly, the Wayland case lacked an explicit X11 driver, and removing each of `xvfb-run`, `Xvfb` and `xauth` failed to stop capture. After the fix all four tests passed, including action-only, headless and simulated macOS launches.
- `python3 -m unittest tests.test_linux_pointer_display tests.test_pointer_routes tests.test_harness tests.test_doctor` ran 67 tests with three skips and no failures.
- A Linux command-line capture with the public pointer route, `DISPLAY=:42`, `--sandbox off` and no `xvfb-run` exited 1 before writing a replay. Its message included `sudo apt-get install xvfb`. In the component-removal test the corresponding command for missing `xauth` was `sudo apt-get install xauth`.
- The public pointer-menu project imported successfully with the installed Godot 4.6.3 and deliberately unreachable X11 and Wayland displays. `godot_import` invoked `--headless --import` and created the project’s import data. The desktop environment is filtered specifically for the rendered capture.
- In Chromium on Linux, **Check folders** showed the Xvfb install command in both project panels. **Verify** showed it again in the rendering warning before creating a job. The check used the loopback app, configured test projects, a version-only stand-in for the pinned engine, and the host’s missing `xvfb-run`.
- An extra run in the order `tests.test_harness tests.test_doctor tests.test_pointer_routes tests.test_app_sandbox` reproduced two sandbox-parity subtest failures on both this change and the original harness at `387a3f33`. A cached host probe reports missing Xvfb where the later fixture expects its simulated missing Bubblewrap. This order is separate from normal test discovery.

## Not done

Live Wayland compositor and native macOS checks were not run.

## Files

- [Godot replay harness](../../harness/run.py)
- [Linux pointer display regression tests](../../tests/test_linux_pointer_display.py)
