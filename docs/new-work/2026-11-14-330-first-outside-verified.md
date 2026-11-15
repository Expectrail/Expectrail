# The first outside game verified with vision (#330)

## What changed

- `docs/outside-projects.md`: the result of run 43652198623, the first vision run whose calibration
  was used. Kinematic-character as pinned accept, broken reject, harmless accept, invisible reject,
  all with the anchored visual observer. The invisible row's reason is stated plainly as indirect.
- `tests/outside/recordings/kinematic-character/calibration.json` and `vision-recording.json`: that run's
  calibration and its 429 recorded answers, both read back with their own readers
  (`anchored.check_calibration`, `recorded.read_recording`).
- `docs/capabilities.json`: a new `outside-projects` row (there was none), status integrated, grade
  diagnostic, with the run as evidence and its limits. `docs/capabilities.md` re-rendered.

## What was run

- The calibration and the recording read back without error; `python3 -m expectrail.capabilities
  check` passes.
- `python3 -m unittest discover -s tests -t .`: 3,554 tests, OK (42 skipped).

## Not done

- Whether a fresh capture reproduces the recorded frames byte for byte (so CI can replay the
  answers), a missing-sprite diagnosis for the hidden player, and a cheaper frame sampling for the
  judge path.

## Files

- `docs/outside-projects.md`
- `docs/capabilities.json`
- `docs/capabilities.md`
- `tests/outside/recordings/kinematic-character/calibration.json`
- `tests/outside/recordings/kinematic-character/vision-recording.json`
- `docs/new-work/2026-11-14-330-first-outside-verified.md`
