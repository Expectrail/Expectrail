# Open a saved menu route in offline binding review (#671)

## What changed

The offline binding review and Check folders now share a reader for the pending setup. It checks the saved route's filename against the digest of the bytes it reads and checks those bytes against init's encoding. For menu projects it checks the saved event shapes, tick range, actions and pointer coordinates against the current project. Opening the review uses saved files for both action-only and pointer routes. The page tells the developer when a route only presses pause and asks them to choose inputs that start and exercise gameplay.

The review still compares bindings and candidates with the current scene, including an explicitly selected player. It accepts older drafts that predate image suggestions and recognizes the earlier wording of the ambiguous-player prompt. The project must still have the same candidates and binding requirements. Projects with deterministic input-map routes still have to match the route init would generate today.

## What was run

- Before the change, `python3 -m unittest tests.test_onboard_saved_route` ran six tests with five assertion failures and one error. The older action-only review reached the game probe, and an invalid pointer reached the input summary before validation.
- A separate regression using the archived six-event init preview failed until the review recognized the earlier ambiguous-player prompt. The same test checks that changing the binding requirement still prevents review.
- The 1,383-byte [archived preview](https://github.com/Expectrail/Expectrail/blob/3c9dcaeb55a35f4dceb7eb7e8276ab43997cf313/2026-11-16-breakout-menu-trial/docs/outside-trials/breakout/evidence/cli/09-init-preview.txt) is an offline test fixture. Its SHA-256 matches the public archive manifest. The archived preview regression also reproduced the old wording failure in Check folders before the two review paths shared their validation.
- With the change, `python3 -m unittest tests.test_onboard_saved_route tests.test_onboard tests.test_menu_routes tests.test_pointer_routes tests.test_inspect_atlas tests.test_app_projects.ConfiguredAppTest` ran 56 tests with three skips and zero failures or errors.
- On two copies of the public game at `0ac7aed444ea593a023d9b666c211d7ab8acd51e`, both reviews exited successfully, made zero game probes and preserved all 107 source file hashes per copy. The browser showed the pause-only guidance on the six-event archived draft and offered zero downloads for its unresolved player. For the 303-event pointer route, the single downloaded config selected the paddle strip, retained its draft flag and contained zero approved checks.
- At main `8ca96a0a` plus this change, Chromium's Check folders showed pause-only guidance on the archived setup and replay guidance on the pointer setup. It started zero probes or jobs and preserved all 107 file hashes in each project. The separate offline review produced the same download counts as above. These were automated checks on prepared copies of the outside game.
- The required historical commit fetch succeeded. On main `8ca96a0a` plus this change, `python3 -m unittest discover -s tests -t .` ran 5,542 tests in 562.621 seconds, with 77 skips and zero failures or errors.
- `python -m agents.export_scan bench docs README.md apps --paths error` scanned 1,251 files with zero errors or warnings.

## Not done

Gameplay replay and human approval are outside the binding review.

## Files

- `expectrail/app.py`
- `expectrail/onboard.py`
- `tests/test_onboard_saved_route.py`
- `tests/fixtures/breakout-legacy-init.json`
- `docs/new-work/2026-11-19-offline-saved-route.md`
