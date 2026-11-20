# Give isolated verification the sandbox probe's recovery advice (#370)

## What changed

When the replay sandbox could not start, the local app told the user to install Godot and Xvfb. The isolated job now gets the reason and remedy from the same probe as `expectrail doctor --isolated`. A missing dependency gets its installation instructions. If Bubblewrap is installed but cannot start, the app directs the user to a Linux host that supports the replay sandbox and gives the doctor command to check that host.

## What was run

- The regression test exercised a missing Bubblewrap executable, a missing Xvfb wrapper and a read-only UID map. All three cases failed on the generic remedy before the change and passed afterward. Each job stopped during preparation with `TOOL_MISSING`, returned `needs-review` and published no output.
- An initial implementation also formatted sandbox version details for successful probes. Three repair tests exposed that their successful probe stand-ins do not carry those details. A fourth test caught missing user-namespace guidance. The final change shares only the recovery message and preserves the successful preflight path. All four existing tests passed unmodified on rerun.
- `python3 -m unittest tests.test_doctor tests.test_orchestrator tests.test_app_sandbox tests.test_platform_tools.SandboxRefusalTest tests.test_ci_autofix.RepairStepTest tests.test_433_remaining.BoundedAutoFix` ran 151 tests successfully with one skip.
- In Chromium, `python3 -m expectrail.cli app` compared the same public kinematic-character base (collision mask 0) against mask 2 and the restored default mask, with **Require the replay sandbox** selected. Both runs stopped in preparation because Bubblewrap could not set up its UID map on this read-only filesystem. Both displayed “Open Expectrail on a Linux host where bubblewrap can start the replay sandbox with user namespaces, then choose Verify again,” followed by the optional doctor command.
- Neither run generated engine observations, vision judgements or a frame for comparison. The renderer probe reported Godot 4.7.2 with OpenGL3 on both sides of its comparison, with Mesa llvmpipe LLVM 19.1.7 locally and 20.1.2 in the public recording. The three project folders remained byte-identical to their starting contents, including the approved check and recording. The browser runs used no provider credentials.
- After the required historical fetch, `python3 -m unittest discover -s tests -t .` completed 5,535 tests with 77 skips and zero failures or errors. The public export scan checked 1,251 files with zero errors or warnings.

## Not done

The public candidate pair still needs a runtime comparison on a host where the replay sandbox starts and the renderer matches the recording.

## Files

- `expectrail/doctor.py`
- `expectrail/orchestrator/engines.py`
- `tests/test_orchestrator.py`
- `docs/new-work/2026-11-20-sandbox-recovery.md`
