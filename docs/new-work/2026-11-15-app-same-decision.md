# Verify kinematic-character from the local app (#370)

## What changed

The recorded-vision option compares a pinned kinematic-character folder with a changed copy. It takes snapshots outside the selected folders and uses the published walk route, approved ground check and calibration. The normal Godot gate runs the game. Its visual observer looks up the frame and point in the published recording. An unanswered question cannot clear a change.

## What was run

The app and `expectrail verify --json` submitted identical requests to separate job stores. A gate with an offline replay and visual observer returned accept for a fix, reject for a regression, and needs-review for a replay that did not finish. The test checks the input digests, app result, CLI decision and CLI exit code in each case.

- `python3 -m unittest discover -s tests -t .` ran 3,721 tests before and 3,724 after. Both ended OK with 47 skips. Neither run had a failing or erroring test name.
- `python3 -m unittest -v tests.test_app tests.test_package` ran 47 tests, all OK. The wheel loaded the route, approved check, calibration and 429 saved answers with Python site packages disabled.
- The pinned-Before refusal test initially got HTTP 201 instead of 400. The first browser run also reported a policy edit because the After snapshot lacked the route and check. A test reproduced the missing After files. Both snapshots now carry the same policy bytes.

### Clicks and result

I used Chromium with the app running in a Linux VM. Before was the public Godot demos' `2d/kinematic_character` at `b761b4cd5718a7118f2c95eb55f181d0a5f004f1`. For After I prepared a disposable copy with `tests/outside/kinematic-character/changes/broken.patch`, which empties the player's collision mask.

1. I entered the two paths, selected **Use the kinematic-character example with recorded vision**, and clicked **Check folders**. Each folder showed a Godot project, one usable route, one approved check and zero drafts.
2. I clicked **Verify**. Job `ebd77bcda81b3270e2258ee73d71c270` ran the pinned Godot with Bubblewrap required. Each replay recorded 180 frames. The recorded observer answered 137 of 138 questions without a model call.
3. I reopened the page, clicked **Open run** under **Past runs**, then **Open this job's evidence viewer**. The page showed **Reject**. The viewer reported the first failure at frame 44. The Before engine check passed, but vision had no answer, so Before was needs-review. The After engine check failed and its visual check was not needed. The recorded comparison was inconclusive and the job verdict was reject. Neither a route nor a spec was reported as changed.

## Not done

A first-time non-developer has not tried this path. The browser check used prepared game folders.

## Files

- `docs/app.md`
- `docs/new-work/2026-11-15-app-same-decision.md`
- `expectrail/app.py`
- `expectrail/app_kinematic.py`
- `expectrail/app_page.py`
- `pyproject.toml`
- `setup.py`
- `tests/test_app.py`
- `tests/test_package.py`
