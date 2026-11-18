# Capture placement and observation completeness (#257)

## What changed

The harness records each captured frame's actual tick interval, draw phase,
viewport and transform. Replay manifests bind that map to the trace and exact
image digests. New observation documents use v1 with per-frame and per-detection
provenance; v0 remains readable. The trusted gate validates capture and observation
completeness before geometry. Missing or shifted evidence and ambiguous singular
identities need review. Pixel boxes rejected by an engine identity filter remain
in the record with their disagreement, rather than disappearing.

New captures use the measured map in the engine, SAM, anchored, template and Unity
observer paths. Legacy fractional clocks without a map are refused. The existing
class-presence meaning of `visible`, plural boundary surfaces, sampling policy,
and answered-not-drawn rule are retained. No approved check was changed.

## What was run

- Required historic fetch, plus the claimed branch and current main, read-only.
- Before: `python3 -m unittest discover -s tests -t .`: 4,565 tests,
  OK, 58 skips, no failures/errors, 412.118 seconds.
- Final after, the same full-suite command: 4,587 tests, OK,
  59 skips, no failures/errors, 459.496 seconds. Failure and
  error names are empty both before and after. The added native-test skip was
  separately exercised with the installed engine and display.
- Focused regression: 322 tests, OK, one named Godot skip. Subsequent producer,
  schema and role regressions also passed; the handover retains every run log.
- Real Godot 4.7.2 with Xvfb: the new 12-tick fixture ran twice at 120/60,
  120/50 and 50/60 ticks-per-second/frames-per-second. All six runs passed:
  every sprite's measured pixel position matched its recorded tick, and both
  runs at each ratio had byte-identical traces and image digests. One test,
  88.645 seconds; mappings are in [the timeline doc](../observation-timeline.md).
- All 4,688 discovered tests load with NumPy and Pillow deliberately unavailable;
  no import errors. The new timeline tests use standard-library PNG fixtures.
- `python -m agents.export_scan bench docs README.md apps --paths error`:
  777 files, zero errors/warnings. New relative documentation links resolve.

The first broader regression attempt exhausted the small disk-backed temporary
filesystem during copy-heavy tests. Subsequent runs used a larger temporary
filesystem. It also exposed schema-reader and class-presence compatibility issues;
those were fixed without changing assertions. The first full after run then found
eight failures in legacy successful-harness stand-ins. Their writers now include
the timeline and valid images. The two files retain all 139 assertion nodes
unchanged, and their 41 tests pass. The unsuccessful logs are included, not
presented as final validation.

## Not done

Native Unity compilation/capture was not run. Unity's 50 ticks/50 frames map is
covered offline, and its writer is included for native validation. The separate
episode normalizer still refuses fractional clock pairs. No live model calls,
recordings, dispatches, workflow edits, game-source edits, approvals, commits,
pushes or GitHub writes. This is Part of #257, pending native Unity evidence.

## Files

- `agents/godot_roles.py`
- `agents/observations.py`
- `agents/sam_anchor.py`
- `agents/sam_observations.py`
- `agents/template_observations.py`
- `agents/unity_observations.py`
- `contracts/examples/observation-timeline.json`
- `contracts/examples/observations-v1.json`
- `contracts/examples/replay-timeline.json`
- `contracts/examples/trace-capture-timeline.json`
- `contracts/observation-timeline.v1.schema.json`
- `contracts/observations.schema.json`
- `contracts/replay.schema.json`
- `contracts/trace.schema.json`
- `docs/new-work/2026-11-16-observation-timeline.md`
- `docs/observation-timeline.md`
- `expectrail/anchored.py`
- `expectrail/evaluator.py`
- `expectrail/gate/verify.py`
- `expectrail/legacy.py`
- `expectrail/observation_timeline.py`
- `harness/godot/expectrail_harness.gd`
- `harness/run.py`
- `harness/unity/package/Runtime/Harness.cs`
- `harness/unity/package/Runtime/Recorder.cs`
- `harness/unity/run.py`
- `setup.py`
- `tests/projects/capture-clock/main.tscn`
- `tests/projects/capture-clock/player.gd`
- `tests/projects/capture-clock/project.godot`
- `tests/test_engine_from_adapter.py`
- `tests/test_observation_timeline.py`
- `tests/test_verify_vision.py`
