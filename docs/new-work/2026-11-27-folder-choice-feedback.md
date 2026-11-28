# Keep the chosen folders’ validation messages when a replacement fails (#803, #710)

## What changed

Each folder’s status region shows the last chooser action and any problem with
the selected path. Choosing an invalid replacement or dropping a file keeps
both paths and their layout warning. If the comparison finishes later, it
can report a missing scene without erasing the chooser error. Editing a
path clears the previous pair’s warning.

## What was run

I ran the full page script in V8 with stand-in DOM elements and controlled
responses from the project APIs. The 48 cases covered Before and After, an
invalid replacement, a rejected drop and cancellation, both reply orders,
a pair with a missing scene and a valid pair, then clearing either field.
The published page at `a333165f` failed 20 cases. All 48 passed with the
change. The actions preserved the selected paths and made zero job requests.
Replacing Before and completing a new valid comparison also cleared the old
scene warning.

## Not done

The Chromium rehearsal now uses the public project fixtures to try an
invalid replacement before and after a real folder check returns. Chromium
and full Linux discovery on this revision are pending.

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/new-work/2026-11-27-folder-choice-feedback.md`
