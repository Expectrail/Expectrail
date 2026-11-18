# A star inside a quoted string is not a YAML alias to the merge guard (#610)

## What changed
The merge guard's line check counts aliases (`*name`) and anchors (`&name`) in a workflow outside
block scalars. It matched `*` after any space, so `- cron: '17 9 * * *'` counted one alias and the
guard labelled #574 `needs-sean` with "the file gains an alias".

`tools/merge_guard.py` now blanks every quoted scalar that closes on its line before it counts, by
YAML's quoting rules: `''` is a quote inside single quotes, a backslash escapes inside double quotes,
and a quote opens a scalar only at the line's start or after a space, `,`, `[`, `{` or `:` (in
`don't` it is a letter). A quoted scalar that does not close on its line is left as it is from its
opening quote, so the count there stays as strict as before. Both `aliases()` and the added-lines
count (`unread_added`) use it, for aliases and for anchors. The parsed reading (PyYAML, aliases
followed) is unchanged.

## What was run
- `python3 -m unittest tests.test_merge_guard` with the change: 109 tests, OK.
- The same tests with main's `tools/merge_guard.py`: the new quoted-scalar test fails 5 ways (the
  cron line single- and double-quoted, `''`, a backslash escape, and the added-lines count).
- The full suite on this branch merged with main: the result is in the pull request.

## Not done
`run-it-nightly.yml` and #574 write the day field as `0-6` to avoid this; they are left as they are.

## Files
- `tools/merge_guard.py`
- `tests/test_merge_guard.py`
- `docs/new-work/2026-11-18-quoted-star.md`
