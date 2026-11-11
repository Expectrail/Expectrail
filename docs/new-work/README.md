# The work log, one file per change

Every change that touches anything outside the docs adds one file here, in the same pull request:

```
docs/new-work/YYYY-MM-DD-short-name.md      for example 2026-11-11-replay-sandbox.md
```

```markdown
# One line: what changed (#issue)

## What changed
What was built or fixed, and why, in plain words.

## What was run
The commands or CI runs, with their results. "Not run" is an acceptable entry; a guess is not.

## Not done
What is left, and what was not run.

## Files
The files that changed.
```

The file is never edited by another pull request, so two pull requests cannot conflict over the log.
Until November 11, 2026 the log was one table, [`../new-work.md`](../new-work.md), and every pull
request added its last row: any two open at once conflicted, three times on November 11 alone. That
table stays as the record up to then and gets no new rows.

The merge guard's check (`python3 -m tools.merge_guard`) asks for an added file with this name and a
"What was run" section. A row added to the old table still passes, for pull requests that were open
when this folder came in.

To read the log in order, list this folder: the names sort by date.
