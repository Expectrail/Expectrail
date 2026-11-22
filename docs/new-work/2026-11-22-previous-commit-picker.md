# Select a previous Git commit as Before (#710)

## What changed

When the developer chooses After first, the local app looks for an existing Before folder. If it finds no sibling or worktree and After belongs to a Git checkout, the developer can open the first parent of the current commit as a temporary Before copy. The page displays the full commit ID. The working copy stays selected as After. Changing the After path clears a Before copy produced for that path. A developer can always choose their own Before folder.

## What was run

- The Chromium regression initially failed because a checkout with no sibling had no previous-commit button. The regression exercises a checkout with a single commit, then one with a readable parent, and checks the file in the nested project directory. The app retains a manually chosen Before path.
- In Chromium 156 at 390 pixels, an automated rehearsal chose a prepared public Breakout game in a nested Git directory using a desktop-dialog stand-in. The checkout had a committed title change and a subsequent uncommitted edit. Activating the button by keyboard displayed the full parent ID. All 109 files in Before matched the original project, and After kept the working edit. The checkout’s HEAD and working files were unchanged. **Check folders** inspected both copies. The page requested one temporary copy and started zero jobs.

## Not done

This covers folder selection on Linux. An unaided developer trial, native macOS and Windows execution, the grant-judge walkthrough and a gameplay verdict were not run here. Inline layout feedback and the visual review remain open on #710.

## Files

- `expectrail/app_page.py`
- `tests/test_app_desktop_chooser.py`
- `docs/app.md`
- `docs/new-work/2026-11-22-previous-commit-picker.md`
