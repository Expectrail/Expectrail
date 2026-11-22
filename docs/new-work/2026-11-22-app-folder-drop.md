# Confirm a dropped project folder in the local app (#710)

## What changed

Dropping a folder from Thunar onto Before used to open a Chromium error tab and leave the field empty. Dropping one folder onto Before or After now opens the existing desktop chooser for that side. The developer confirms the full path in the dialog. The page never uses the dropped folder's name as a path. Cancelling keeps the previous selection.

## What was run

- On November 22, `python3 -m tests.test_app_desktop_chooser` failed before the change because the first folder drop left Before empty. It passed after the change. The drop rehearsal used two same-named projects and a stand-in dialog. It checked both fields, cancellation, an ordinary file, multiple folders, and a drop outside both fields. It recorded three empty-body chooser requests, one tab and zero jobs.
- On Linux, automated pointer drags from Thunar 4.20.2 into Chromium 156.0.8078.79 opened the real Tk chooser twice. Selecting `RoundOne/OrbitGame` for Before and `RoundTwo/OrbitGame` for After filled each field with its respective absolute path. The browser stayed on one tab with zero page errors. The app received two chooser requests and created zero jobs.

## Not done

The desktop dialog still requires a selection. Chromium provided the directory name and a browser handle but no absolute filesystem path in the native drop. The native run covered Linux. An unaided developer trial and native runs on macOS and Windows remain open.

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/app.md`
- `docs/new-work/2026-11-22-app-folder-drop.md`
