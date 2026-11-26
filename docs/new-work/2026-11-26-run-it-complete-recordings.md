# Refuse incomplete Run it replacement recordings (#830)

## What changed

The writer checks that each distinct image digest, question kind, and prompt has a successful answer before touching the destination. Repeated identical questions use the same coverage entry, and successful empty detections count as answers. A run with unanswered questions stops before writing. The proposal check already refuses a recording with no answers. The recording format and exact-match replay are unchanged.

## What was run

- The offline budget-stop test failed on the original writer because it accepted the partial recording. With the change, it reports unanswered questions and preserves the existing complete file.
- The complete control uses identical frames and successful empty detections. It passes the proposal check and has fewer stored answers than requests.
- All 59 Run it, recorded-renderer, and combat-recording tests passed on Linux. Full discovery ran 6,109 tests and passed with 57 skips on base `9a89f06`.

## Not done

The refreshed live answers and deployment are tracked by #823. This change used offline fixtures.

## Files

- `expectrail/recorded.py`
- `expectrail/runit.py`
- `tests/test_runit.py`
