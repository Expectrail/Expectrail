# Show whether vision judged the public checks in current and past runs (#370)

## What changed

The app reads the per-version visual results in the saved public checks. A configured observer can be skipped when the engine already failed a check. If every applicable result says `not-asked`, the app says that vision was never asked about those checks. A live observer that judged only some results or returned no usable answer gets the corresponding explanation. A recorded lookup that returned no answer still counts as a lookup. The saved decision is preserved when the run is reopened.

## What was run

In the [public outside-game rehearsal](https://github.com/Expectrail/Expectrail/issues/370#issuecomment-7038227074), both versions failed the engine check at frame 44 in the rejected mask-2 comparison. Both per-check visual results were `not-asked`. The paired anchor was a separate measurement. I checked the successful [hosted gate regression](https://github.com/Expectrail/Expectrail/actions/runs/46053163659/job/140689218849) that asserts an engine rejection, a `not-asked` visual result and zero requests to the configured visual observer. On `5a8f4dba`, the app selects its recorded-lookup or model-judged wording from the configured provider in this case.

The new HTTP test uses the public replay fixture, with a falling player in both versions. It checks the reject decision and zero recording lookups, then verifies the explanation before and after reopening the job. The formatter cases cover skipped routes, an absent Before, missing answers, partial vision verdicts and an attempted recording lookup. The existing accepted-repair test now checks partial coverage when Before fails on the engine and retains the original full-coverage assertion for a clean comparison on both sides.

Focused Python execution and full Linux discovery on this change are pending.

Guard: test change intended (#370)

## Files

- `expectrail/app.py`
- `tests/test_app.py`
- `docs/new-work/2026-11-27-app-public-vision-results.md`
