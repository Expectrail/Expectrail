# Resume binding review after init (#260)

## What changed

When init writes a pending binding review, configured verification now directs
the developer to **Check folders** in the local app and identifies the unresolved choices. A draft that
requests a player texture gets the field name and the required `res://` path
format. The verifier still stops before creating a job. It reads the draft only
for guidance, using the existing size-limited reader and strict JSON parser.

## What was run

- Before the change, two regression tests failed because verification told the
  developer to run init again. The cases used an image-less player and two
  possible players.
- On a disposable Crate Run copy with its shipped config removed, ordinary
  `init --dry-run` found the player and no texture candidates. `init` saved
  `expectrail.project.draft.json`. On base `43b8106`, the changed
  `verify --project GAME` exited 5 and named `bindings.player.texture` and the
  local app’s **Check folders** action. It left the project byte-for-byte
  unchanged and created no job store.
- In Chromium, selecting **Check folders** on the same project showed
  “Saved draft preview for crate” and “Player: no saved sprite texture found.”
  Both folders displayed the required `bindings.player.texture` field. The
  job history contained zero jobs and every project file retained its digest.
- `python3 -m unittest -v tests.test_pending_project_setup tests.test_app_projects`
  passed all 19 tests on `43b8106`.
- After fetching the historical fixture commit,
  `python3 -m unittest discover -s tests -t .` ran 5,422 tests in 521.766 seconds,
  with 76 skipped and no failures.
- `python3 -m agents.export_scan bench docs README.md apps --paths error` scanned
  1,236 files with zero errors and zero warnings.

## Not done

Crate Run draws its player as a filled polygon. A developer still needs to
choose a representative image and review the route. Its shipped check is a
draft. This rehearsal supplied no new check approval or gameplay verdict.

## Files

- `expectrail/project_job.py`
- `tests/test_pending_project_setup.py`
- `docs/new-work/2026-11-19-pending-project-guidance.md`
