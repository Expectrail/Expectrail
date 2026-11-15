# Warn before using recorded vision on another renderer (#515, second part)

## What changed

Built on the first #515 rendering-provenance change. Doctor compares the current empty-project
renderer probe with a configured project's recording; the local app displays the same comparison
and asks the user to read a warning before creating a job. Exact answers and all gate rules remain
unchanged. Added a strict capture-job drift check and a re-record guide with actual saved-answer
counts and historical spend, not a new cost estimate. No workflow file was edited.

## What was run

Before full suite on current main plus the adapted first patch: 3,940 tests, 422.046 seconds,
0 failures, 0 errors, 45 named skips. The new offline comparison/doctor/app tests pass, including
Chromium at laptop and phone widths. The real empty-project probe reports Godot 4.7.2, opengl3,
llvmpipe LLVM 19.1.7. The strict real drift check fails as intended: kinematic was recorded under
20.1.2, and all four Run it recordings lack provenance. Final full suite: 3,962 tests, 447.110 seconds,
0 failures, 0 errors, 46 named skips. Failing test names before and after: none;
no new failing names. The extra skip is the new capture check's missing pinned Godot installation.
All prior skip names/reasons are unchanged. Before/after logs and exact comparisons are in the handover.
Final targeted renderer/doctor/app/package/work-log run: 90 tests, OK (two named engine skips).
The capture check also reached the expected real provenance failure with Python's site packages
excluded (`-S`), so the capture job needs no extra Python dependency installation. A race in the new
browser test was fixed by waiting for uniquely numbered replies; its request-count assertions are
unchanged. Three repeated browser checks passed. Recorded-only doctor checks now state plainly
that no live key/cap is required, without the inherited live-provider needs-review message.

## Not done

No live model, dispatch, spend, new recording, approval, commit, push or GitHub write. No native
macOS/Windows or human usability trial. CI on this patch has not run. Sean must recover original
capture provenance or re-record the four legacy Run it recordings before enabling the supplied
capture-job step; unknown metadata deliberately cannot pass. A matched renderer is not proof of
complete recorded image/question coverage. The original first-part work log remains unchanged.

## Files

- `expectrail/renderer.py`: shared probe composition, project readiness and strict recording scan.
- `expectrail/doctor.py`: retain structured probe data internally; project comparison in existing output.
- `expectrail/app.py`, `expectrail/app_page.py`: show readiness before starting the configured job.
- `setup.py`: include the shared module in the installed app/doctor.
- `tests/test_recorded_renderer_drift.py`: stand-ins, browser checks and real capture drift guard.
- `docs/recorded-renderer-upgrades.md`: re-record steps, counts, costs and rollout limitation.
- This work log. The handover lists the separate first-part dependency files and its generic-project
  observer integration for main's merged #370 change.
