# Measure false rejections on a harmless source change (#675)

## What changed

The public counting audit can replay each frozen trace check against the clean platformer and against the mutation bench's registered comment-only edit. It records the two arms separately, compares three repetitions per arm and requires complete coverage for every probe the check names. A changed failure is attributed to the edit only when all three clean observations pass and all three changed observations fail.

The optional audit writes one result per check, identifies unrun and indeterminate cases, and retains the captured trace and manifest for each repetition. The existing gate, counting rules, strong-catch classification, registration and approvals receive no control inputs.

## What was run

The focused regressions exercise attribution, incomplete probe coverage, mixed repetitions, failed engines, absent custom routes and a schema-valid route with the wrong digest. The ordinary counting audit reproduced 24 defects and 137 advisory rows, including 91 kept by the legacy rule and 46 dropped. Its generated page retained SHA-256 `5a7e608fe590a7f047fe32295ffdacbc3bf80934cf8ba1d7aea04c14b9b3a247` (verified against the committed audit).

The required historical fetch succeeded. `python3 -m unittest tests.test_jit_harmless_control` passed all 3 tests. `python3 -m unittest discover -s tests -t .` ran 5,423 tests in 523.935 seconds, with 76 skips, zero failures and zero errors.

The optional public audit ran all 137 frozen checks against the registered edit: 135 pass, zero false rejections, two indeterminate and zero unrun. Hash checks covered all 216 headless replay manifests and traces. Re-evaluation from the retained traces reproduced all 137 row identities, outcomes and provenance. The public export scan covered 1,225 eligible files, with zero errors and zero warnings. The separate scan of the 32 changed files and public inputs also returned zero errors and warnings. No model or hosted workflow ran.

[The measurement](../measurements/675-harmless-control.md) names the command, exact public route artifacts and per-check results.

- `python -m agents.export_scan bench docs README.md apps --paths error` scanned 1,238 files with zero errors and zero warnings.

## Not done

This measures one comment-only change and the frozen public trace predicates. It does not estimate a general false-rejection rate for art changes, alternative gameplay implementations or other games. The other pieces of #675 remain open.

## Files

- `expectrail/jit/counting.py`
- `expectrail/jit/assess.py`
- `tests/test_jit_harmless_control.py`
- `docs/jit.md`
- `docs/measurements/675-harmless-control.md`
- `docs/new-work/2026-11-19-harmless-control.md`
