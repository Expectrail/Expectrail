# Keep the layout warning after cancelling the folder chooser (#803, #710)

## What changed

When the selected After copy is missing the Before version's entry scene,
cancelling the desktop chooser now keeps the layout warning beside After.
It also confirms the cancellation. Editing a folder clears the old pair's
warning. Cancelling on a valid pair keeps the usual cancellation message.

## What was run

On #813 head `f2fa3ca2`, I ran the page's JavaScript folder handlers in
V8 with stand-in fields, a controlled folder-check response, and a
cancelled chooser response. A single cancellation, a repeated cancellation,
and a folder-check response during the dialog all erased the warning.
The selected paths did not change.

With the correction, those three cases retained the missing scene name.
The valid-pair control still reported cancellation, and typing in the
field during the dialog preserved the edit. Clearing the other folder
removed the stale warning. Each case made one pair check, with one chooser
request per cancellation and zero job requests. The full page script
parsed in V8.

## Not done

The Chromium rehearsal now opens and cancels the After chooser with the
two mismatched public test projects. It checks both paths, the cancellation,
and the missing scene name before clearing Before. Chromium and full
Linux discovery on this tree are pending.

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/new-work/2026-11-27-chooser-cancel-layout-warning.md`
