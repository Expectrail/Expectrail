# The merge guard's workflow rule counts what a diff adds and compares the parsed file (#291)

## What changed
#278 merged with three known ways past the workflow rule in `tools/merge_guard.py`, all of one shape: the
guard read a workflow line by line and compared totals for the file, so something taken away in one
place paid for something added in another, and a line could mean something to YAML that the line
reading did not see. This changes the approach instead of adding a pattern for each case.

- **The file is parsed and compared.** When PyYAML is there, the workflow as it was and as it is are
  parsed (aliases followed, escapes decoded, quotes closed where YAML closes them) and compared job by
  job: the events under `on`, the secrets each job's text and the workflow's text name, each job's
  `environment`, its permissions and `id-token`. What the line reading has not already said of the same
  job is reported with ", as the parsed file reads (the line reading did not see it)".
- **Where the parsed reading cannot be made, that is a reason.** A file PyYAML cannot parse, one key
  twice in a mapping, `jobs` or `on` under two spellings, a file that is not a mapping, a job that is not
  a mapping, or a file too large once its aliases are followed gives
  `cannot tell: read this workflow: <why>`. Without PyYAML every changed workflow gives that reason: the
  line reading alone is no longer passed. The tool still installs nothing, and its last printed line says
  whether PyYAML was there.
- **Escapes, aliases and anchors are counted on the lines the diff adds**, not as the file's totals. An
  anchor (`&name`) was not counted at all before. A moved line is reported too, which is the strict side.
  The totals are still compared as well.
- **`_strip_comment` skips the character after a backslash inside double quotes**, so `\"` no longer
  closes the guard's quote where YAML's stays open.
- The line reading and the counts of the words in the raw text stay as they were.

Three assertions in existing tests changed, none loosened: where a test adds `x-extra: &p {...}` the
expected list now also holds the new anchor reason.

## What was run
- The review's cases against main's copy of the tool (`origin/main` at bdccc2d) and against this branch,
  through `check_workflows`: on main each returned no reasons (the escaped trigger on `fix-matrix.yml` and
  on `web-fix.yml`, an alias swapped for another, an anchor moved with no alias touched, the escaped
  quote). On this branch each is reported.
- `python3 -m unittest tests.test_merge_guard tests.test_new_work`: 108 tests, OK.
- `python3 -m unittest discover -s tests -t .` on this branch, which is on main at bdccc2d: 2,004 tests,
  17 skipped, OK.
- `python3 -m tools.merge_guard --base origin/main --head HEAD`: two reasons, both `needs-sean: guard`,
  because this change edits the guard and its tests. That is the tool working as written.
- Every workflow in `.github/workflows/` (27 files): PyYAML parses each, the parsed reading and the line
  reading agree on each job's secrets, permissions, `id-token` and environment, and three ordinary edits
  to each give no reasons. That is a test now.

## Not done
- Not run: any of these workflows on GitHub itself. What GitHub's own reader takes differently from
  PyYAML is not covered (PyYAML reads YAML 1.1 and follows `<<`).
- Not shown: whether the runner of the `merge-guard` job has PyYAML. The job installs nothing. If it has
  not, every pull request that changes a workflow gets "cannot tell" there until the job installs it,
  and `merge-guard.yml` is a file only Sean changes. The job's last line says which it is.
- A secret a job already names in its script and newly uses a second time is still not seen: the gain
  is read per job, in both readings.
- A quoted string that runs over a line and a line that is not a plain key are still compared as
  totals for the file. The parsed reading covers what they could hide; the messages do not name them.
- `AGENTS.md` does not say that a pull request that changes the guard needs a person; the tool says it.

## Files
- `tools/merge_guard.py`
- `tests/test_merge_guard.py`
- `docs/new-work/2026-11-12-workflow-rule-added-lines-and-parsed.md`
