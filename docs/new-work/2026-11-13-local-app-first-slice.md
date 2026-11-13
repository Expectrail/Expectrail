# A local app for verifying two Godot folders (#370)

## What changed
`expectrail app` serves a page on 127.0.0.1 at a free port. It prints an address with a random
session token. Every request checks the Host and token; API actions require POST and a token
header. No CORS access is enabled. Only this session's reports and their PNG copies are served;
links and path traversal are refused, and report scripts are blocked.

The page checks two folders using the existing check reader, then creates a request and job
through the existing orchestrator. It shows recorded phases, cancellation, decisions, errors
and a link to the existing report. The orchestrator was not changed. The evidence viewer has
only a named placeholder. The page and server are included in the package.

## What was run
- Python 3.12.14. The required pinned-commit fetch succeeded.
- Before editing, `python3 -m unittest tests.test_app.CommandTest` ran one test and failed:
  the command returned 5 and said there was no command named app.
- Before editing, `python3 -m unittest discover -s tests -t .` ran 2644 tests: 7 failures,
  8 errors and 25 skipped. The failing/erroring test identities match the 15 accepted
  environment failures from #365.
- The new command-error tests were also run before their fixes: one failure (invalid options
  exited 2) and one error (a bind failure escaped). Both now return 5, without a verdict.
- `python3 -m unittest tests.test_app tests.test_package`: 36 tests, OK. These include HTTP
  requests against FakeReplay and the orchestrator stand-ins, cancellation of a worker and its
  child, every result state, security checks, and HTTP from the installed wheel with no external
  packages. Tracebacks and replay warnings in this log are the deliberately broken stand-ins.
- A subprocess check of `python3 -m expectrail.app`: printed a token address, served HTTP 200,
  and exited 0 on Ctrl+C. The token was not saved in the log.
- `node --check` on the extracted inline script: exit 0. This checks syntax, not rendering.
- After the final code change, `python3 -m unittest discover -s tests -t .` ran 2663 tests:
  7 failures, 8 errors and 25 skipped. The same 15 tests fail/error before and after; a comparison
  of their full test identities found no new failures and none missing.
- A Node check of the page script with stand-in DOM and fetch objects passed: result wording,
  unfinished state, a late status response after cancellation and connection recovery. This is
  not a browser or a rendering check.
- `git diff --check`: exit 0. The merge guard's `check` function, on all eight uncommitted
  changed files: zero reasons. The committed-head guard command is for Sean after his commit.

- Validated by the architect session on Ubuntu with Python 3.13.18, on main at 51e1fb8:
  `python3 -m unittest discover -s tests -t .` on unchanged main ran 2700 tests, OK (27 skipped);
  with this change, 2719 tests, OK (27 skipped). `tests.test_app tests.test_package`: 36 OK.
  `python3 -m expectrail.app` served the page (HTTP 200), refused a request without the token
  (401) and one with another Host (403).

## Not done
Not looked at in a browser. No Godot game was run. No outside developer or nonterminal-user
trial was done. No Git reference picker, evidence viewer, past-runs screen or installer was
built. No model calls were made. CI was not run here; Sean must publish the branch and wait
for every check to be green. GitHub was read only; no claim comment, commit or PR was posted.

## Files
- `expectrail/app.py`
- `expectrail/app_page.py`
- `expectrail/cli.py`
- `setup.py`
- `tests/test_app.py`
- `tests/test_package.py`
- `docs/app.md`
- `docs/new-work/2026-11-13-local-app-first-slice.md`
