# A release workflow, and the README leads with the installed command (#333)

## What changed
- `.github/workflows/release.yml`, "Release". It builds the wheel for a version tag and attaches it to the
  run.
  - A tag `v<version>` builds only when it is the package's own version. Any other tag builds nothing and
    says why. A dispatch builds from main only.
  - The wheel is installed into a clean venv, and its `--version` must say "installed package" and the
    version.
  - The wheel and its SHA-256 go up as an artifact.
  - It has `contents: read`, no secret and no environment, and it publishes nowhere.
- `README.md`: a "Use it" section right after the opening picture. It has Run it in the browser, then
  `pip install .`, `expectrail doctor` and `expectrail sample`. It says what each gives: `sample` uses no
  key today, so it decides the same with or without one, and vision by default is #379. It cites the
  `package` job of CI run 43476504903, which did all of this from an installed copy.
- `docs/install.md`: a section on the release workflow. It has not run.
- The capability ledger has an `installed-command` row (grade `diagnostic`, status `integrated`). It cites
  that run, whose job `package` and every one of its steps succeeded, read from the API. The nightly
  platform test had noted on #333 that the ledger had no row for `doctor` or `sample`.
- `tests/test_release_workflow.py`, 9 tests:
  - The workflow's triggers and permissions, and that it holds no secret and publishes nowhere.
  - The order of its steps, and that its actions are pinned.
  - The version step run in bash: the right tag builds; a wrong tag, the bare version, a pre-release
    suffix and a bare `v` build nothing; a dispatch from a branch other than main builds nothing.

## What was run
- `python3 -m unittest tests.test_release_workflow tests.test_capabilities`: OK.
- The build steps by hand: `pip wheel . --no-deps --no-build-isolation`, then install into a new venv.
  `expectrail --version` said `expectrail 0.1.0 (installed package; ...)`. `pip install -r
  requirements-build.txt` could not find `setuptools==80.9.0` from this machine's index, so the build
  used the setuptools already installed. CI's `package` job installs the pin.
- The full suite on the branch merged with main at 0db693e: 2,994 tests, OK, 27 skipped. The first run had one failure, `tests.test_python_floor`: that test expects the README's first stated minimum in the form "Python 3.12+", so the new section now says it that way.

## Not done
- The workflow itself has not run. A tag push is a person's step, and so is publishing to PyPI.
- "In a clean container" from the issue: the `package` job's clean venv on a hosted runner is the nearest
  run.
- `--jobs-root` after the command (#383) is not changed here.

## Files
- `.github/workflows/release.yml`
- `README.md`
- `docs/install.md`
- `docs/capabilities.json`, `docs/capabilities.md`
- `tests/test_release_workflow.py`
- `docs/new-work/2026-11-13-release-readme.md`
