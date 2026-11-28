# Check a recent folder when its partner is cleared during lookup (#803)

## What changed

When someone picks a recent folder second and clears the other field before the
server replies, the app checks the remaining folder on its own. A moved project
or an unfinished setup can then show its warning beside the path. Replacing the
recent selection while the request is pending discards its result.

## What was run

I ran the published page handlers from `c905043e` in V8 with stand-in fields
and controlled folder-check replies. With a moved or draft recent folder on
either side, clearing its partner immediately or while the paired reply was
pending lost the warning in eight cases. The same checks passed when the reply
arrived before the edit.

The changed handlers passed all 48 cases. They covered both sides, moved and
draft folders, valid folders and layout mismatches, three reply timings, and
keeping or replacing the selected path. The layout warning cleared when the
pair was broken.

The Chromium rehearsal now holds the paired reply on the local server, clears
the opposite field, then releases the reply and checks the moved-folder warning
for each side.

## Not done

Independent Chromium and full Linux discovery results are pending on #803.

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/new-work/2026-11-28-interrupted-recent-folder-check.md`
