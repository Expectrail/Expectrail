# Find the repair controls from a rejected run (#370)

## What changed

When a rejected run has no repair record, the app now names the checkbox
and spending limit a reviewer can use on a new run. The same summary
appears in Past runs. Previously it directed the reviewer to a command-line
flag. A run with repair activity still shows its recorded state and review.

## What was run

On November 22 the new loopback HTTP test failed on main `21fabcbefb2e`
because the reject summary contained `--auto-fix` and omitted the checkbox
label. With the fix, the test passed for the result and for history read
from another session. Two existing tests for the repair record and the CLI
and viewer wording also passed. All three passed in a fresh environment
with the test dependencies and without NumPy or Pillow.

An installed wheel on Linux ran the bundled clean and fall-through folders
through the app. In job `77349f63e6d0803c6bf46760e6896164`, Godot 4.7.2
reported pass then fail. Chromium 156 showed Reject and opened the same
summary from Past runs after a reload. Selecting the named checkbox revealed
the named spending limit. Exactly one job was created, repair stayed off
for that job, and vision was not asked. Both project tree digests stayed
unchanged. Chromium recorded zero page errors and zero external requests.

## Not done

The unaided participant trial remains open. The browser rehearsal did not
submit a repair.

## Files

- `expectrail/app.py`
- `tests/test_app.py`
- `docs/new-work/2026-11-22-app-repair-guidance.md`
