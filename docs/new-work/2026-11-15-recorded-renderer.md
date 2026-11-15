# Recorded vision rendering provenance and measured limits (#515)

## What changed

The vision-recording schema and example add optional renderingEnvironments. The writer records
engine, version, renderer and device from the answered capture, including unknown provenance;
old recordings remain readable. Missing images under differing known environments name both
versions in the client, observer, app/outside judge, Run it and paired-comparison reasons.
The gate and anchored observer's decision rules are unchanged. No approximate match was added.

The existing kinematic recording gains its original capture environment only; every answer is
unchanged. Public real PNG/manifests and an offline measurement tool reproduce a table of renderer
variation and hidden, moved, resized and recoloured player probes. A sparse recolour overlaps the
renderer drift's global pixel/count range, so exact matching remains the only policy.

## What was run

Read #515 and its claim, AGENTS.md, the recording paths and public capture evidence. Started on
chatgpt/515-recorded-renderer from origin/main 282f3c8de018672c93ecbed4a9e061fde7f93ed0.
Ran the required historical fetch. The baseline full suite ran 3,904 tests in 380.944 seconds:
1 failure, 0 errors, 45 skips. The failing test was
 tests.test_replay_sandbox.DiskBoundTest.test_a_folder_the_game_makes_unreadable_is_cannot_tell.
It reported the disk limit instead of the expected unreadable-directory text; its separate
unchanged rerun passed. Final full suite: 3,923 tests in 424.889 seconds,
0 failures, 0 errors, 45 skips. There are no new failing test names; the same
45 skipped tests have the same reasons. Both logs and exact named comparisons are in the handover.
Final focused suite: 152 tests in 31.097 seconds, OK; final contract/renderer/work-log set:
31 tests in 1.260 seconds, OK.

The offline measurement tool reproduced 179 identical frames and one frame with 2 pixels changed
by 1 channel level, 261.017 to 266 pixels from the player. The two-pixel player recolour has the
same count and channel difference, at distance zero. The complete table, sources and method are
in docs/recorded-renderer.md and docs/measurements/recorded-renderer.json.

Re-judged the two saved real captures with the existing recording and calibration: original check
pass (120/120 answered); newer capture needs-review (111/112 answered before frame 111 stopped
it), naming LLVM 20.1.2 versus 19.1.7. This used saved frames, not a new engine or model run.
The full outside judge on the original saved captures kept pinned/harmless accept and
broken/invisible reject: 841 of 860 questions answered. The 19 unrecorded paired questions
were on the invisible arm, whose missing-player check still rejected. These were offline queries.
Focused tests cover old/new recording contracts, writer/reader, missing capture metadata,
renderer/engine differences, mixed banks, exact matching of every visual probe, error redaction,
anchored and paired explanations, and the normal Run it status/findings path. The existing
schema-pattern regression gains a matching sample for the new printable renderer-string pattern;
its newline-refusal assertions remain unchanged.

## Not done

No opt-in tolerance: the global difference ranges overlap for a sparse recolour. The spatial
separation of these fixtures is not a validated general safe policy. No unchanged-game accept on
both renderer builds is claimed. No new engine run, live recording, model call, spend, approval,
commit, push or GitHub write. gate/verify.py, anchored.py and .github/ are untouched. No human
browser trial or native macOS/Windows run. CI on this patch has not run.

## Files

- .gitignore
- contracts/examples/vision-recording.json
- contracts/vision-recording.v1.schema.json
- docs/measurements/recorded-renderer.json
- docs/new-work/2026-11-15-recorded-renderer.md
- docs/recorded-renderer.md
- expectrail/app_kinematic.py
- expectrail/gate/anchor.py
- expectrail/recorded.py
- expectrail/runit.py
- tests/fixtures/recorded-renderer/README.md
- tests/fixtures/recorded-renderer/hidden.png
- tests/fixtures/recorded-renderer/recorded-replay.json
- tests/fixtures/recorded-renderer/recorded.png
- tests/fixtures/recorded-renderer/replayed-replay.json
- tests/fixtures/recorded-renderer/replayed.png
- tests/fixtures/recorded-renderer/source.json
- tests/fixtures/recorded-renderer/tinted.png
- tests/outside/recordings/kinematic-character/vision-recording.json
- tests/test_recorded_renderer.py
- tests/test_schema_pattern.py
- tools/outside_vision.py
- tools/recorded_renderer.py
