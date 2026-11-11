# The work log is one file per change, so two pull requests no longer conflict over it

## What changed
Every pull request added a last row to the one table in `docs/new-work.md`. Any two pull requests open
at once therefore conflicted in that file, and each conflict cost a manual merge, a push and a new CI
run before the merge guard could look again. On November 11 it happened three times: #300 and #302
against #301, then #302 against #300's fixes, then #304 against #301. GitHub does not apply
`merge=union` from `.gitattributes` to pull requests, so that setting would not have helped there.

Now each change adds its own file under `docs/new-work/`, named `YYYY-MM-DD-short-name.md`
(`docs/new-work/README.md` has the layout). No other pull request touches that file. The old table
stays as the record up to November 11 and gets no new rows.

`tools/merge_guard.py` asks for an added entry with that name and a "What was run" section. A row
added to the old table still passes, so the pull requests open at the switch (#300, #302, #304) need
no change. `AGENTS.md`, `CONTRIBUTING.md` and the pull request template say the same.

## What was run
- `python3 -m unittest tests.test_merge_guard tests.test_new_work`: OK.
- The full suite, `python3 -m unittest discover -s tests -t .`: 1,719 tests, OK, 10 skipped.

## Not done
- The scheduled agents' own instructions still say "add a row to docs/new-work.md". They are updated
  when this merges; until then a row still passes the check.
- The other files several pull requests tend to touch at once (`docs/capabilities.json`,
  `.github/workflows/ci.yml`) merge by themselves in most cases and are left as they are.

## Files
`docs/new-work/README.md`, `docs/new-work.md`, `tools/merge_guard.py`, `tests/test_merge_guard.py`,
`tests/test_new_work.py`, `AGENTS.md`, `CONTRIBUTING.md`, `.github/pull_request_template.md`
