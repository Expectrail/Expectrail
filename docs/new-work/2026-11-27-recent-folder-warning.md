# Keep a moved recent folder’s warning while editing the other path (#803)

## What changed

Reopening a recent folder whose `project.godot` has moved shows a warning beside its path. The app now keeps that field’s own warning when a developer edits the opposite path or abandons a comparison. Editing the affected path clears its warning. A newer completed comparison can supersede the earlier finding. A warning that depends on the two folders’ layouts expires when that comparison changes.

## What was run

I ran the complete page script in V8 with stand-in DOM fields and controlled folder-check replies. Starting with a stale recent folder, typing in the opposite field and then erasing it preserved the warning on the PR base `e75394e7`. The published head `9d2fb86c` lost it on both Before and After.

Across 32 cases the published head failed eight and the correction passed all 32. The cases covered either field, an incomplete comparison, a completed comparison, a late response, replacing the affected path, and clearing a warning after a newer check. These handler checks started zero jobs.

The Chromium regression extends the existing moved-folder rehearsal. It keeps the selected After path, edits Before, waits for a completed pair check, then clears Before and checks the original warning. Chromium and full Linux discovery on this correction are pending.

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/new-work/2026-11-27-recent-folder-warning.md`
