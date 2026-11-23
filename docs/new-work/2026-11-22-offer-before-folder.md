# Offer a Before folder when a developer selects After first (#710)

## What changed

With Before empty, selecting an After folder can reveal a neighboring project or a copy in a registered Git worktree. The local app shows the candidate’s full path and where it came from. Choosing **Use as Before** fills the field. The developer can also choose another folder. Editing either path dismisses the suggestion and invalidates any pending suggestion for the old selection.

The desktop chooser, including a confirmed folder drop, a recent After folder, and leaving a manually edited After field all use the existing project check. **Check folders** and **Verify** still perform their normal checks.

## What was run

- Before the change, `python3 -m unittest tests.test_app_desktop_chooser` failed in Chromium. Choosing the configured After project left its neighboring Before folder undiscoverable.
- After the change, `python3 -m unittest tests.test_app_desktop_chooser tests.test_app_project_picker` passed all seven tests. Chromium 156.0.8078.79 showed the full sibling path at 390 pixels, accepted it by keyboard, and displayed the smoke route for both projects after inspection. The rehearsal also checked recent and typed After paths, an existing manual Before choice, a late response after Before was edited and cleared, and zero verification jobs.
- A separate Chromium run dropped an After folder onto the field and confirmed it through a desktop-dialog stand-in. The candidate matched the project subfolder in a real registered Git worktree. Before stayed empty until the button was clicked. The only POSTs were the chooser and project check.
- An automated rehearsal at 390 pixels used two prepared copies of the public Breakout project. Selecting the recent After folder offered its Before sibling. Pressing Enter selected it, and **Check folders** displayed the draft setup. Both project directories had the same content digests after inspection as before. The page started zero verification jobs and made zero external requests.

## Not done

The previous-commit fallback and the visual review of the first screen remain open under #710. These automated browser runs used Linux. An unaided developer trial, native macOS and Windows runs, and a grant-judge walkthrough were not run here.

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/app.md`
- `docs/new-work/2026-11-22-offer-before-folder.md`
