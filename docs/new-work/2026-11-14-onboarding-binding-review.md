# Review and save draft game bindings offline (#331)

## What changed

After init, onboard turns a saved draft and its first route into one local page.
It shows bound objects, project images and route actions. A link under each
eligible Dodge player image downloads a complete config with that choice.
Each config stays draft. The page contains no JavaScript.

## What was run

The installed wheel generated pages for the bundled game, kinematic-character
and Dodge the Creeps. Chromium Headless Shell 150.0.7871.181 opened all three
offline with JavaScript disabled at 1,280 px and 390 px. One link for each
platformer and all four Dodge links downloaded reader-valid draft configs at
both widths. No HTTP(S) requests were observed. The 10 focused CLI tests passed.

The full suite ran 3,600 tests before and 3,604 after. Both ended in OK
with 51 skips. Both lists of failing and erroring tests were empty.

## Not done

Human minutes from init to a saved draft: **not measured**. The facilitator
steps are in docs/first-user-test.md. Check approval and gameplay verification
remain separate. Hosted CI was not run.

## Files

- `docs/first-user-test.md`
- `docs/new-work/2026-11-14-onboarding-binding-review.md`
- `expectrail/cli.py`
- `expectrail/onboard.py`
- `expectrail/onboarding.py`
- `setup.py`
- `tests/check_onboard_games.py`
- `tests/test_onboard.py`
