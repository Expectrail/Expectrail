# Show a missing folder before Verify (#370)

## What changed

Verify focuses the first empty Before or After field and tells the person which folder to choose. It checks both paths before inspecting the game or submitting a job. The existing retry guidance still applies if the app loses a response after it has submitted a job.

## What was run

On November 21, real Chromium with a prepared kinematic-character Before folder reproduced the first-session stop. On the original page an empty After caused two inspections (including confirmation of the renderer warning) and one job submission. The server created zero jobs. The page said it could not confirm whether verification started and suggested looking in Past runs.

On the changed page, the same action sent zero requests, focused After, and showed “Choose the After folder or enter its path.” The browser regression also checked an empty Before and a whitespace-only After. The existing screen regression passed, including the lost-reply case.

The outside-game rehearsal used the [documented preparation](../app.md#try-kinematic-character-with-saved-vision-answers) with Godot demos at `b761b4cd5718a7118f2c95eb55f181d0a5f004f1`. Chromium 156 drove both chooser buttons, Check folders and Verify, acknowledging the renderer warning. Only the native folder dialog was replaced with predetermined choices. The loopback server, worker and Godot 4.7.2 replay were real. No paths were typed. Job `c98d62242f6ef85e06f4c6093156a204` finished **needs-review**. The one engine check passed. The recorded visual observer lacked an exact image answer on llvmpipe LLVM 19.1.7 for the recording made on LLVM 20.1.2. Both folder digests matched their values before the run. Chromium reported zero page errors.

## Not done

This was an automated Linux run using two prepared, identical copies of a public game. No live model ran. Installing and using Expectrail without help on a developer's own game still needs a person.

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/new-work/2026-11-21-app-missing-folder.md`
