# Run the timed quickstart in CI and explain its prerequisites (#268)

## What changed

Built `chatgpt/268-quickstart-ci` from the local first-user branch, fast-forwarded to main `191cc3d7145202df42fbeee9a5b80d9e7622166d`, and reapplied the unchanged first-user handover. That parent branch was not yet published remotely. The handover names this composed baseline and includes the parent patch separately; no commit was created.

Added `quickstart-timing` beside `capture-smoke`: Ubuntu 24.04, Python 3.12, pinned shared apt/Godot actions with restore-only caches, Xvfb and Mesa prerequisites, and the unchanged timer under `xvfb-run`. No secrets, protected environment, wider permissions or kernel-setting change. Timer/engine-resolution failures fail the job. Timings and diagnostics upload with `always()` even after an incomplete attempt.

README and quickstart now name the virtual-display packages, Mesa packages and 1 GiB disk threshold, explain OpenGL not tried and the optional sandbox, and keep the vision settings deliberately absent. All six executable command blocks and the README install command are unchanged. Doctor's disk fix now repeats the minimum; its sandbox fix names Xvfb when the actual blocker is missing Xvfb. Decision rules and thresholds are unchanged.

Recorded prerequisite audit (from the first-user handover's doctor.json):

| Finding | Entry docs before | Doctor before | This change |
| --- | --- | --- | --- |
| Display missing: no xvfb-run | Quickstart said virtual display; README linked prerequisites | Named xvfb-run and suggested installing xvfb | Name Xvfb/xauth in both pages and provision them in CI |
| OpenGL not tried because display missing | Quickstart named software OpenGL; README did not | Correctly reported not tried and told the reader to fix prerequisites | Explain not tried, add Mesa package names; keep doctor behavior |
| Disk: 533 MB free, 1024 MB required | Neither entry page stated the minimum | Named locations and threshold; fix only said free some space | State 1 GiB in both pages; repeat 1024 MB in doctor's fix |
| Sandbox unavailable because display missing; optional here | Sandbox limits linked, optional status not explained in quickstart | Named missing Xvfb but suggested installing bubblewrap | Explain optional status; point the fix at Xvfb |
| Vision key missing intentionally | Both explained no-key behavior | Named MODEL_API_KEY and its fix without revealing a value | Keep deliberately absent; test unchanged diagnostics |
| Vision cap missing intentionally | Both explained the required cap for accepting | Named EXPECTRAIL_SAM_USD_CAP and its fix | Keep deliberately absent; test unchanged diagnostics |

The earlier proxy error was a timer environment-filter bug already fixed in the parent, not a further missing machine prerequisite. Godot 4.7.2, Python, patch, curl and unzip were present in the recorded doctor output.

## What was run

- Read AGENTS.md; fetched the required baseline SHA and main. Composed before-change suite: 3,566 tests in 798.423 seconds, OK with 37 existing skips.
- Focused new job/prerequisite tests plus existing doctor, timer, quickstart, apt and download tests: 90 tests in 4.358 seconds, OK with one existing real-engine skip. The shell test executes the actual CI run block with offline executables and checks success, incomplete timer exit 2, and engine-resolution exit 7.
- First focused attempt caught the front-door ledger's refusal to advertise an unlisted EXPECTRAIL_TOOLS switch. Docs now direct readers to doctor's folder settings; doctor retains the exact setting names. Existing tests were not edited or weakened. Both logs retained.
- New job permissions and existing workflow settings checked; published command blocks compared exactly. Final full-suite: Before: 3566 tests in 798.423 s, OK (skipped=37). After: 3575 tests in 754.960 s, OK (skipped=37). Failing names/kinds are empty before and after, with no new failures and the same 37 skips. Nine new offline tests account for the increase; existing tests/parent files are unchanged. The incremental patch applies to the composed baseline, applied bytes match the worktree, and the real index is unchanged.
- CI run/timings: **not run**. No published new head/PR/run was found; this local job cannot produce a PR CI result until the architect publishes it. No run URL, conclusion or timings are invented.

## Not done

No complete local replay measurement: the recorded host lacked display and disk prerequisites; the new CI job is the requested place to run all six steps. CI remains not run until the PR exists and the job completes. The handover tells the architect to read the run and job conclusion before citing its artifact's actual times. A completed walkthrough still has the documented no-vision decisions; it is not a game accept or human first-user session. The human session still needs Sean or Timothy.

Browser review: **not looked at**. Real Chromium launched but file navigation was blocked by administrator policy; no screenshot result is claimed. No native macOS/Windows run, paid model call, key added, approval, commit, push or GitHub write. No dossier, anchored observer, outside-vision, jit workflow, project config/receipts/init/inspect, repair or auto-fix file was edited. Completed synthetic test output was removed only to free disk; sources and logs retained.

## Files

- `.github/workflows/ci.yml`
- `README.md`
- `docs/quickstart.html`
- `expectrail/doctor.py`
- `tests/test_quickstart_ci.py`
- `docs/new-work/2026-11-14-quickstart-ci.md`
