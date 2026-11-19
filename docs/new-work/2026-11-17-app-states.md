# Explain every local app job state (#370)

## What changed

The app presents a waiting screen while a job is queued, phase progress while
the worker runs, and distinct results for stopped, cancelled, blocked and
decided jobs. Each gives a next action. A job that completed as needs-review
without evidence displays the reason it could not be carried out. The saved
decision and command-line exit remain needs-review. A needs-review with findings
still leads to evidence. Earlier sessions show saved details and distinguish
evidence they cannot open. The app's loopback and token rules still apply.

The Linux wheel install instructions provide a single paste to create a local
Python environment, install the downloaded wheel and open the app. A default
browser opener is opt-in at the command. The terminal displays the local
address if opening the browser fails. The documented flow needs a prepared
machine and uses Terminal for launch. Sean's trial script records where a
first-time participant stalls and what they understand from the two results.

Guard: test change intended (#370)

## What was run

Base 791f50b99b1e6a11e262088ed8b56255fa2494ad. The required historical fetch completed.
Both full runs used `python3 -m unittest discover -s tests -t .` with
EXPECTRAIL_* unset. The baseline checkout stayed untouched during validation.

Baseline ran 4,764 tests in 808.945 seconds. FAILED (failures=1, skipped=62).

After ran 4,767 tests in 836.762 seconds. FAILED (failures=1, skipped=64).

The existing `tests.test_orchestrator.ProcessTest.test_waiting_on_a_worker_that_died_reports_it_at_once`
case uses a 0.5-second bound that includes process cleanup. A focused diagnostic
reproduced it at 1.258 seconds, including 1.249 seconds in real cleanup and three
`/proc` scans. The app patch leaves that test and the orchestrator unchanged.

The focused app/project/browser set ran 40 tests and passed. The existing
renderer-warning browser test passed separately. The new browser test first
reproduced the queued-message gap. A first development rerun also exposed a
test fixture error reading the history object as a list. Reading the submitted
job's ID corrected the test and the final run passed.

With pinned Godot 4.7.2 and Xvfb on the configured engine path and PATH,
`EXPECTRAIL_ENGINE_TESTS=required python3 -m unittest -v tests.test_app_engine`
ran the real Crate Run browser demonstration and sample parity. The outside case is recorded in `docs/demo/local-app.md`.
The bundled sample app and CLI job input digests and findings matched for the
bug (reject, exit 1) and fix (needs-review, exit 2).
The fix passed the engine check. This offline run had no vision answer.
Both new test modules loaded with numpy and PIL imports blocked.

Reported, not recorded here: the builder's local run of the literal install command (November 17)
from an empty temporary home, with the wheel in Downloads, dependency fetching disabled and a
controlled browser opener. Its output is not in this pull request, and it was not run in CI.

The public projection passed `python -m agents.export_scan bench docs README.md apps --paths error`.
Prohibited paths were excluded by metadata before opening.

## Not done

Sean's unassisted non-developer trial, a published desktop installer, automatic
system prerequisite installation, and Git commit or working-copy selection are
still open. The offline real-replay comparison should be read with its
observer and replay isolation settings. No model call, GitHub write or
deployment was made.

## Files

- expectrail/app.py and expectrail/app_page.py
- tests/test_app_engine.py and tests/test_app_screens.py
- docs/install.md, docs/demo/local-app.md and docs/trials/370-first-user.md
