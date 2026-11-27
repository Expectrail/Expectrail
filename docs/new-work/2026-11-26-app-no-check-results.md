# Explain an empty set of public check results in Past runs (#370)

## What changed

When a completed run has a findings record with no approved public check
results, the local app now says so. The old wording credited the configured
observers even when the result had no checks. The change is in the app's
explanation of the saved result.

## What was run

On `be55ce93`, I passed an empty checks folder from a temporary public
project to the Godot gate. I ran the gate in process, saved its result with
the job store, then reopened Past runs. The replay was a stand-in and the
visual observer used the bundled recording bank. Neither received a call.
The gate returned needs-review with the reason “no checks ran”. Past runs
said the verifier used the engine and looked up vision answers.

The three configurations in `tests.test_app.ObserverWordsTest` failed
against the original app source and passed with the change. I repeated
the saved-history check with both an empty and a populated checks folder.

| Public results | Replay calls | Recording lookups | Decision | Past runs |
| --- | ---: | ---: | --- | --- |
| 0 | 0 | 0 | needs-review | “This run has no results from approved public checks.” |
| 2 | 4 | 8 | needs-review | Said the verifier looked up vision answers in the recording. All eight lookups missed. |

The public export scan checked 1,396 files with zero errors and warnings.

Guard: test change intended (#370)

The added regression checks the explanation for zero public results with a
recorded observer, a model provider, and an engine-only configuration.

## Not done

Full-suite verification of this follow-up is pending. The background job
worker could not start its timer threads on this Linux host. A separate
Python process on the host could start zero of 64 requested threads.

## Files

- `expectrail/app.py`
- `tests/test_app.py`
- `docs/new-work/2026-11-26-app-no-check-results.md`
