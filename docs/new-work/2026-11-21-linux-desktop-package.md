# Open Expectrail from Applications on Ubuntu 24.04 amd64 (#249, #370)

## What changed

The desktop package installs the existing wheel, its command and a system Applications entry.
Ubuntu resolves the replay and folder-picker dependencies. The menu entry starts the local app
with the system Python in isolated mode and hands its loopback address to the default browser.
The CI package job builds and tests this candidate without distributing it.

## What was run

- Built the wheel and the Debian package offline after installing build dependencies. The package
  tests compare wheel contents and permissions, inspect package metadata, and load the app outside
  the checkout with the system interpreter. The three package tests and two launcher tests passed.
- Installed the local package with APT on a disposable Ubuntu 24.04.5 amd64 container. The
  installed command reported version 0.1.0. The desktop file passed `desktop-file-validate`.
  As an unprivileged user, both the installed desktop command and `gio launch` handed the
  authenticated Before and After selection page to a stand-in browser. Ubuntu's system Python
  was 3.12.3. Removing the package removed the menu entry and command.
- Ran the installed verifier on Crate Run, the project maintained in this repository for
  integration tests. A clean container could not fetch Godot because its HTTPS trust store
  rejected the test network's certificate chain. With the official 4.7.2 archive supplied
  in the user cache and checked against the pinned SHA-512, the replay ran. One engine check
  passed, vision was not asked, and verification returned `needs-review` (exit 2).
  The container could not start Bubblewrap and reported zero sandboxed replays out of one.

## Not done

An actual graphical package-manager session, an unaided developer's elapsed time, and a verdict
on their own game were not run. Public distribution and additional operating systems remain open.

## Files

The package builder is `tools/build_deb.py`, permitted by the tools allowlist in `.gitignore` and using
`requirements-build.txt`. The tests are `tests/test_debian_package.py` and
`tests/check_installed_desktop.py`. The Ubuntu package job is in `.github/workflows/ci.yml`.
The developer instructions are in `docs/install.md` and `docs/app.md`.
