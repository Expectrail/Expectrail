# The spend-cap audit resolves each cap's value and reads shell command strings (#627)

## What changed
The merge guard found three ways `tools/spend_cap_audit.py` passed a step that may start a capped
sender with no cap, or an empty one (#627). Each is fixed by changing how the audit reads the case, not
by one more special case:

- **A cap's value is resolved, not collected** (`cap_at_start`). Before, the audit took the union of
  every name set non-empty at the workflow, job and step level and in `$GITHUB_ENV`, so an empty value
  at an inner level never unset an outer one. Now the innermost `env:` that names the cap decides (an
  empty or null step value unsets the job's or workflow's), and the last sure `$GITHUB_ENV` write of it
  in the job wins (a later empty write unsets an earlier one). The audit does not rely on which of
  `env:` and `$GITHUB_ENV` the runner applies last: the cap counts only when both, where named, set it.
- **Every `$GITHUB_ENV` write must be read, or the caps are "cannot tell"** (`github_env_writes`). A
  write counts only as `echo NAME=value >> $GITHUB_ENV` or a `cat` here-document of `NAME=value` lines
  that surely runs. Any other mention of `GITHUB_ENV` (`printf`, `tee -a`, `exec >>`, a group, a
  pipeline, a condition, the `NAME<<EOF` form, `>`, a line it cannot read), a shell script it follows
  or one of our modules it may start that names `GITHUB_ENV`, a start it cannot follow, and a step with
  `if:` or `continue-on-error` leave every cap "cannot tell" for later steps that otherwise set it. A
  local composite action (`uses: ./...`) is read the same way. Where nothing sure sets the cap, it stays
  listed as missing.
- **A shell started by name is read** (`_shell_start`). `bash -c '...'`, `sh -ec "..."`, `bash -e
  script.sh`, `bash <<EOF` and nested shells are read as scripts in turn, and a changed environment
  (`sudo bash -c`) is still named. `eval`, a command line built by `xargs`, `parallel`, `find` and the
  like, and a shell whose command is a variable (`bash -c "$SCRIPT"`) are "cannot tell".

The tests in `tests/test_spend_cap_audit.py` hold each of the guard's probes and the wider cases
above. No workflow on main is written in any of these ways: `--check` lists the same 48 steps with no
drift notes, so `tools/spend_cap_gaps.json` is unchanged.

**A correction to `2026-11-18-spend-cap-audit.md`.** Its "What changed", second paragraph, says a cap
counts when set "by `export`". That is wrong since 3e45126: a step's own script never sets a cap, and a
step whose script names a needed cap is "cannot tell" for it (as the file's third paragraph and the
code say). The correction is recorded here because a change's work-log file is never edited by another
pull request (`docs/new-work/README.md`, `AGENTS.md`).

## What was run
- `python3 -m unittest tests.test_spend_cap_audit`: before the fix, the new tests failed (25 failures,
  7 errors on main 32c416d, which contains 3e45126); after it, 62 tests, OK.
- Six mutations of the audit (empty values ignored, unread writes trusted, `-c` strings not followed,
  `if:` ignored, `eval` allowed, a may-not-run write not merged): each made the suite fail.
- `python3 -m tools.spend_cap_audit --check` on the branch: "48 step(s) listed; they match the recorded
  list.", with no drift notes. The same on main before the change.
- The full suite: see the pull request.

## Not done
- An action from outside the repository, or a JavaScript or Docker action, that writes `$GITHUB_ENV`
  is not read, and neither is a program other than a shell script or our Python. The module docstring
  says so.
- The 47 `unreviewed` entries and setting each sending step's cap stay on #267.

## Files
- `tools/spend_cap_audit.py`
- `tests/test_spend_cap_audit.py`
- `docs/new-work/2026-11-18-spend-cap-audit-gaps.md`
