# Select the bundled trial games in the local app (#370)

## What changed

Sean can prepare two project folders for the first-user trial with one command from
the checkout. Each folder opens directly in **Choose Before folder** or **Choose
After folder**. The participant card now uses the graphical install steps and
the default project screen. The facilitator tool uses the same public game,
fall-through patch, smoke route and existing approved ground check as the CLI sample.

## What was run

On November 22, 2026, on Debian 13 with main `7c08b926`:

- With the old trial's `sample.checkout` layout, inspecting the game folder inside
  either version found zero usable routes and zero approved checks. Both configured
  copies made by the new tool listed `smoke` and `player-stays-above-ground`.
- `python3 -m unittest tests.test_app_trial_folders` passed both tests in a fresh
  venv without Pillow, NumPy or jsonschema. The first regression failed before the
  preparation command existed. A second regression first reproduced a dangling
  destination link redirecting the output. Repeating the command now preserves
  an existing destination, including such a link. The route and approved check
  in each copy matched the bundled files byte for byte.
- Built `expectrail-0.1.0-py3-none-any.whl` offline and installed it in an empty
  venv without dependencies. Wheel SHA-256 was
  `368e07560e1263eb6aa9ed046ff8fd3483b2f4395452fcfec2f0c3b5645f5cde`.
  Started its installed `expectrail app` outside the repository. Chromium
  156.0.8078.79 drove the two native Tk folder dialogs under Xvfb, selected
  **Check folders** and **Verify**, and opened the evidence viewer for each job.
  Godot 4.7.2 replayed the game. The vision key and spend cap were unset.

| Before → After | Installed app job | Ground check, before → after | Vision | Result in both the app and the viewer |
| --- | --- | --- | --- | --- |
| Clean → Broken | `a6b02b71a39606665f464ef9d3396c59` | pass → fail | not asked | Reject |
| Broken → Clean | `b5086917326997466a6c16eafc5580e0` | fail → pass | not asked | Needs review |

Both jobs completed. Both viewers named the ground check. The browser recorded
zero external requests and zero page errors. The two project tree hashes were
unchanged after the runs and matched the job inputs.

| Input | SHA-256 |
| --- | --- |
| Clean tree | `87f6ebc80961cc51c68276ffd52512241d7f2a9d1956459352c5c5feb7ff85e2` |
| Broken tree | `b1d8ec23184e1544c19b0c259b26afa723b7211d2a4b51ba3643f383a637a20e` |
| Policy, both comparisons | `e33e2e55e757ce21914854ef1d2e05724b158c9d425f66267f3f888eb2fac8db` |

Full discovery (`python3 -m unittest discover -s tests -t .`) passed with 6,040
tests run and 57 skipped in 1,093.555 seconds. The export scan of `bench docs README.md apps` checked 1,368 files with zero errors and zero warnings.

## Not done

Sean still needs to observe someone who has never used a terminal install the
desktop package, verify both comparisons and explain the results unaided. The
automated rehearsal used a wheel installed from a terminal. Acceptance of the
repair with independent vision was outside this no-spend run.

## Files

- `tools/prepare_app_trial.py`
- `tests/test_app_trial_folders.py`
- `docs/trials/370-first-user.md`
- `docs/new-work/2026-11-22-bundled-app-trial.md`
