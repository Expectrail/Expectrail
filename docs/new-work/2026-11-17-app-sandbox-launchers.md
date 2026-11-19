# Show replay sandbox decisions and reopen the local app from a launcher (#370)

## What changed

Stacked on #370's PR (#620). The local comparison continues to submit the normal
verification job. The app offers the CLI's isolated execution class with the
**Require the replay sandbox** checkbox and renders the shared isolation
wording from findings. A preflight refusal shows needs review and the
worker's diagnostic, including its reason and fix. The default diagnostic
mode still follows the worker's usual sandbox rules.

The documented one-paste wheel install now creates the launch entry for that
Python environment. Linux uses the applications menu or a desktop entry.
macOS uses an executable command file in the user's Applications folder.
Its Terminal window opens automatically. Each launcher starts the existing
local server and obtains a new browser URL.

Guard: test change intended (#370)

## What was run

Latest main ran 4,900 tests in 865.402 seconds. OK (skipped=66).

After the stack ran 4,906 tests in 859.139 seconds. OK (skipped=68).

Both full runs had EXPECTRAIL_* unset. The former worker-cleanup timing failure was absent in both full runs. The exact test also passed separately on latest main in 2.670 seconds.

- The historical fetch succeeded after the first attempt returned HTTP 503.
- The missing-Bubblewrap regression first failed for the missing sandbox label
  and because the app ignored the isolated choice. The final focused app
  and project run passed 43 tests, including the Chromium screen and GIO
  launcher cases (reported from the builder's local run; in CI the launcher cases
  run and the Chromium screens test skips). The GIO path test caught an executable
  path containing a percent sign and passed after using a fixed executable with a
  quoted path argument (tests/test_app_launcher.py, run in CI).
- A real [Crate Run parity run](../demo/local-app.md#sandbox-parity-follow-up)
  hid only Bubblewrap discovery. Both ordinary workers refused the isolated
  run with needs review and returned reject for the diagnostic run. The
  browser showed the same reason and replay counts as the CLI's evidence.
  Godot 4.7.2 and Chromium ran locally. No vision settings were supplied.
- Reported, not recorded here: the builder's local install run (November 17), from an empty
  Linux home and again over an earlier same-version wheel, with desktop-file-validate and
  Chromium. Its output is not in this pull request; not run in CI. Shown in CI: GIO launching
  the `.desktop` entry, and the `.command` file under a POSIX shell (tests/test_app_launcher.py). All three affected
  test modules loaded with numpy and PIL blocked.
- The export scan on this pull request's tree: 0 errors (architect, November 18).

## Not done

Finder and macOS replays, the native desktop install on an unprepared machine,
and Sean's non-developer trial remain untested. Linux's launcher starts a local
server that can persist after the browser closes. No push, deployment, live model
use, or approval change.

## Files

- expectrail/app.py and expectrail/app_page.py
- tests/test_app_launcher.py, tests/test_app_sandbox.py and tests/test_app_screens.py
- docs/install.md, docs/demo/local-app.md and this work log
