# Show when replay errors left a check without observations (#370)

## What changed

The local app now reads the Before and After outcomes in each saved check
before describing who judged it. When every attempted replay stopped, the
result says those checks have no engine measurements or vision answers.
When only some stopped, it explains the gap for the affected version.
The same text appears when reopening a past run.

## What was run

On main `de1ddd65`, saved public sample jobs
`1d317fd9e7ca4cdb52f202ade04378af` and `a2a9999f54b1f02ccc35953d8da82cfa`
had zero completed replays, yet the app attributed every check to both observers.
The new HTTP regression failed on both the partial and complete replay-stop
cases. It uses a stand-in replay and exercises the active result and history.
After the fix, `python3 -m unittest -v tests.test_app tests.test_app_screens`
passed all 30 tests in 35.944 seconds.

An offline Linux rehearsal installed two wheels built from 321 source inputs,
one from main and one with the app change. The installed sample command ran
with recorded vision configured and the display launcher unavailable inside
the replay sandbox. All three sample jobs finished with a needs-review decision
and zero completed replays. Chromium 156 opened each saved job in both apps.

| Job | Message on main | Message with this change |
| --- | --- | --- |
| `f1c1e576a83e5d4f536ef98490ad3820` | Both observers judged every check | No replay finished |
| `a65587c7b2811d9724b71db2b86cf089` | Both observers judged every check | No replay finished |
| `f96d325fadff5c8ae335cee9483b1831` | Both observers judged every check | No replay finished |

The nine request, status and findings file digests matched before and after
the six opens. Chromium made zero POST requests, made zero external requests
and reported zero page errors.

## Not done

The unaided trial with a person new to the terminal remains open.

## Files

- `expectrail/app.py`
- `tests/test_app.py`
- `docs/new-work/2026-11-23-app-replay-attribution.md`
