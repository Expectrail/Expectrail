# Tell the reviewer when the sample used saved vision answers (#370)

## What changed

The public sample keeps its clean, broken and repaired vision answers in a
bank. The local app recognized the provider description for an individual
recording but missed the bank's `recorded: ` prefix. Opening a sample job
therefore credited the engine and vision model without telling the reader
where the vision answers came from.

The result now says the verifier looked up answers in the recording and
made no live model call. A stopped replay still reports the gap in observations.

## What was run

The new HTTP regression failed on `826bca49` with “The engine's record and
the vision model judged every check.” It exercises the actual bundled bank
with a stand-in replay that finishes and another that stops. It checks both
the active job and what a new app session reads from disk.

With the fix, `python3 -m unittest -v tests.test_app tests.test_app_screens`
passed all 31 tests in 37.178 seconds. The new regression also passed in a
Python 3.12 venv without NumPy or Pillow.

On Linux, the wheel from `826bca49` ran the bundled sample with recorded
vision. All three findings identified the provider as
`recorded: clean, fall-through-bug, fall-through-repair`. Chromium 156
then reopened each job in two offline-installed wheels using the same store.
Only the updated app identified the saved answers on all three screens.

| Sample | Job | Decision in both apps | Completed replays |
| --- | --- | --- | ---: |
| Clean | `8302a8cca5d7c07821c2bacf427971f8` | accept | 1 |
| Fall-through | `72ecef2880c356e648134a7480537200` | reject | 2 |
| Repaired | `e6565bcd3583de47eb3e8f03a292db79` | accept | 2 |

All nine request, status and findings digests matched after the six opens.
Chromium made zero POST or external requests and reported zero page errors.

## Not done

The unaided trial with a person who has never used a terminal remains open.

## Files

- `expectrail/app.py`
- `tests/test_app.py`
- `docs/new-work/2026-11-24-app-sample-recording.md`
