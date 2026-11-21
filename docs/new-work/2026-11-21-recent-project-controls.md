# Reuse a local project folder in the app (#710)

## What changed

Before and After each offer the folders the local app has already remembered. Choosing one fills that side and checks the current path with the existing authenticated project API. Moving or removing a game can leave a stale entry. The field shows the problem and lets the person select another folder. Editing the field clears its previous setup review and discards late validation replies.

## What was run

On November 21 the browser test failed on the original page because it displayed zero recent choices after the native picker had recorded three folders. On the changed page Chromium 156 selected a remembered folder on each side and reopened the local page. Removing one project's descriptor gave a correction next to the affected field. Editing the field before the check returned preserved the edit. The run used a stand-in native dialog, sent six chooser requests, created zero jobs, recorded zero page errors and fit a 390-pixel viewport. The five HTTP project-picker tests passed.

## Not done

An unaided developer has yet to time this path. This slice covers history selection. Dragging folders and offering a derived Before folder remain separate work.

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/app.md`
- `docs/new-work/2026-11-21-recent-project-controls.md`
