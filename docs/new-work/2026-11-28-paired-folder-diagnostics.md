# Keep a folder’s own warning when it was selected second (#803)

## What changed

A developer can fill Before, select a moved After folder from Recents, and see that its `project.godot` is missing. Clearing Before used to erase that warning. Selecting the moved Before folder second caused the same problem.

The paired check now marks the After warning that depends on Before’s entry scene. The page remembers each folder’s own diagnostic from the paired response. Changing the other field clears a layout mismatch. Replacing the affected folder or getting a clean result clears its earlier diagnostic.

## What was run

I ran the page script in V8 with stand-in form controls and controlled folder-check replies. Four of 14 cases failed on published head `c07920fc`. Both a missing project descriptor and a draft setup lost their warnings on either side when the affected folder was selected second. The PR base `7eeec431` kept the folder’s warning in those four cases.

The correction passed all 14 cases, including both selection orders, clearing the other field, changing the affected path, a subsequent clean check and the After layout mismatch. These handler checks started zero jobs. The new Chromium assertions exercise a moved folder selected second on each side. Independent Chromium and full Linux discovery on this tree are pending.

## Files

- `expectrail/app.py`
- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/app.md`
- `docs/new-work/2026-11-28-paired-folder-diagnostics.md`
