# From no config to a verdict: the setup rehearsal, and a config that can judge nothing is refused up front (#260)

## What changed

- `python -m tools.setup_rehearsal --project bundled|crate-run --out DIR` is #260's Done-when run, kept
  repeatable. On a disposable copy with its config removed it runs `init --dry-run` (no file changes),
  `init`, `verify --project` on what init wrote, the person's step, then `verify --project` on the
  unchanged game and on a seeded bug. The person's step is taken by the rehearsal on the copy and is
  recorded as such: the player's image where init could not choose one (Crate Run's crate is a
  polygon; it takes `res://crate.svg`, the image the shipped config names), `draft` removed, and
  `agents/specs/player-stays-above-ground.json` named in `approvedContracts`, copied unchanged with
  the approval it already has. Nothing is approved. Vision settings are removed from every command's
  environment, so no model is called. It writes `setup-rehearsal.json` and prints a table.
- `expectrail verify --project` now refuses, before any replay, a base config that names no usable
  route or no approved check. It exits 5, starts no job and names the field to fill (`routes`,
  `approvedContracts`), says when the named checks are drafts nobody approved, and that a draft
  config from init must be reviewed. Before, the run replayed for minutes and ended "no checks ran",
  or "no route files match routes/*.json (head)", a folder the developer never wrote. With
  `--with-heldout` it goes on to the gate, since held-out checks can judge. The app's path is
  unchanged (`project_job.prepare` is not touched).
- CI's `capture-smoke` step that runs `tests.test_second_project` also runs `tests.test_setup_rehearsal`,
  so Crate Run's rehearsal runs with Godot and the sandbox required. No permission, secret or
  environment changed.

## What was run

- The rehearsal on both projects, on this machine (Godot 4.7.2, xvfb, no bubblewrap so replays ran
  outside the sandbox, no vision key), at 8ca96a0 plus this change. Both ended as expected (exit 0):

  | Project | init wrote | Route | verify on init's output | Unchanged game | Seeded bug |
  | --- | --- | --- | --- | --- | --- |
  | Bundled game | a draft config (player `Level/Player`, image `res://player/robot.webp`) | 2,094 ticks, 66 events | exit 5: no approved check; config is a draft | exit 2 needs-review, the engine's check passes, no vision, 320 s | exit 1 reject (`physics-fall-through/v1`), 302 s |
  | Crate Run | a review draft: no saved image for `Player` | 243 ticks, 10 events | exit 5: choose the image in Check folders | exit 2 needs-review, 19 s | exit 1 reject (crate moved without collision), 23 s |

  So, with the person's step, the config `init` proposes verifies on both projects: the bug is
  rejected and the unchanged game is held at needs-review because no visual observer was asked.
  No accept was tried: that needs a vision key and spend.
- `python3 -m unittest tests.test_project_unready tests.test_setup_rehearsal -v`: 17 tests, OK; the
  Crate Run rehearsal test ran with Godot (47 s).
- `tests.test_pending_project_setup tests.test_app_projects`: 19 tests, OK.
- Three mutations of the refusal (refusing held-out runs too, dropping the draft-config line,
  reading the head's config instead of the base's) were each caught by `tests.test_project_unready`.
- Full suite on this branch with main at 8ca96a0: 5,673 tests, OK, 44 skipped (1,929 s).

## Not done

- An accept on either project: it needs a vision key and a spending cap.
- The bundled game's shipped `game/platformer/expectrail.project.json` names no routes and no checks,
  so `verify --project` on it is now refused with what to add. Adding them is an edit to
  `game/platformer` (Sean's) and the check choice is a person's.
- When a player is drawn with no image (Crate Run), the review page offers no image to choose; the
  rehearsal takes that step itself. `calibrate` stays with #330.
- The bundled game's rehearsal takes about ten minutes and is not in CI.

## Files

- `tools/setup_rehearsal.py` (new)
- `tests/test_setup_rehearsal.py` (new), `tests/test_project_unready.py` (new)
- `expectrail/project_job.py` (`unready`), `expectrail/orchestrator/cli.py` (the refusal)
- `.github/workflows/ci.yml` (one more test module in an existing step)
- `docs/project-config.md`
- `docs/new-work/2026-11-20-setup-rehearsal.md`
