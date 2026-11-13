# Match the documented Python minimum to the package (#335)

## What changed

The README now requires Python 3.12+, matching `pyproject.toml` and `docs/install.md`.
The package requirement itself is unchanged.

`tests/test_python_floor.py` reads the minimum from `pyproject.toml` and checks every recognised
minimum in the README and install guide, including the guide's table. Either document naming
no minimum fails with its filename. The parser accepts a minor version beside Python with
"Requires", "+", or "or later/newer"; it does not treat a tested version as a minimum.
Tests cover lower and higher versions, missing statements, partial versions, a conflicting table
row, and a copy of the README with 3.10+ restored.

The repository-wide search found no other incorrect current minimum for Expectrail. The doctor
already uses 3.12; `setup.py` supplies no separate minimum; the site has no additional minimum.
The `_bmad` helper scripts declare their own interpreter requirements, separate from the
Expectrail package. Those declarations and historical run records were left as they were.

## What was run

- `python3 --version`: Python 3.12.14.
- `git fetch --no-tags --depth=1 origin c169a5e0da304773587304ed47bc8aabcec80da7`: succeeded.
- Before the wording fix, `python3 -m unittest tests.test_python_floor`: 8 tests, 1 failure.
  The README check reported 3.10 instead of the package's 3.12. This failure was read before the fix.
- After the fix, `python3 -m unittest tests.test_python_floor -v`: 8 tests, OK.
- `python3 ../Expectrail-335-handover/prove-readme-regression.py`: the real README test ran on a
  temporary copy with 3.10+ restored. 1 test, 1 expected failure, exit 1. The README was not edited
  by this check. The helper and its output are in the handover.
- Before: `python3 -m unittest discover -s tests -t .` on main
  `70caaa043d263395990b4994bff45786a95d6e48`: 2707 tests, 7 failures, 8 errors, 25 skipped.
  All 15 entries match the accepted missing-tool and sandbox-limit baseline.
- After: the same full-suite command: 2715 tests, 7 failures, 8 errors, 25 skipped. The result
  summaries were read. The same 15 failure/error entries occur before and after, including
  multiplicities; no new failures or errors. Both logs and `compare-suites.py` are in the handover.
- `python3 ../Expectrail-335-handover/check-working-tree.py`: the merge guard's `check` function
  examined all 3 changed files; 0 reasons. This is a working-tree check, not the commit-based CLI.
- `git diff --check`: no whitespace errors.

- **Validated by the architect session** (separately from the builder's runs above), on Ubuntu with
  Python 3.13.18, main at `9ac971e`: `python3 -m unittest discover -s tests -t .` on unchanged main
  ran 2785 tests, OK (27 skipped); with this change, 2793 tests, OK (27 skipped), with no failures or
  errors on either side. `tests.test_python_floor -v`: 8 OK. `prove-readme-regression.py`: 1 test,
  1 failure ("README.md: minimum Python 3.10 differs from pyproject.toml requires-python >=3.12"),
  exit 1, as expected. `git diff --check`: clean.

## Not done

CI must be green before the pull request is ready. The builder's local suite had 15 accepted
environment failures; the architect session's run on Linux was clean.
No runtime requirement, workflow, engine behaviour or support for an older Python was changed.

## Files

- `README.md`
- `tests/test_python_floor.py` (new)
- `docs/new-work/2026-11-13-python-floor.md` (new)
