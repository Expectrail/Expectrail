# Verify a configured project in the local app (#370, slice 4)

## What changed

The app reads expectrail.project/v1 and shows its routes, approved checks and draft warnings.
The app and CLI's new verify --project option share project_job.prepare, snapshot both games,
copy selected policy bytes unchanged and submit the ordinary verify request. The base config
chooses the policy for both sides; changing it on the head cannot clear the change. The existing
draft-config needs-review rule is unchanged. Explicit-path verification remains available.

An optional project.visual request field selects recorded anchored vision from regular recording
and calibration files inside the base game. The schema, example, producer and normal Gate reader
are included. There is no live fallback. Invalid evidence cannot accept, and missing exact image
questions are named in the worker log. The example helper now prepares a normal configured folder;
it has no pinned base-tree rule, worker or verification function. Existing approved bytes are copied
unchanged. No approval or spec meaning was added or changed.

## What was run

Read AGENTS.md, #370 and its comments, #502 and its discussion. Started from pushed branch
chatgpt/370-app-any-project at b9476356356d715341212bff74f8224cdab2a14d (current main at fetch).
The required historical fetch was run. Baseline full suite: 3,865 tests in 478.211 seconds,
OK with 45 skips and no failures or errors. Full before/after logs and named comparisons are
included in the handover. After: 3,877 tests in 399.930 seconds, OK with 45 skips and
no failures or errors. Failing/error test-name sets are empty on both runs; skipped names
and reasons are identical.

Focused app, config, intent and installed-wheel tests passed (87 tests in 33.752 seconds). The final configured
project module passed 12 tests, including a second project with different paths, app/CLI input
and decision parity, draft refusal, base-policy selection, exact unchanged check bytes, local
recorded answers through the normal worker, missing evidence and linked-policy refusal.

A real Godot 4.7.2 replay of the pinned public kinematic-character and a configured app job
reproduced the missing question. Chromium was used at 1440x900 and 390x844. Check folders listed
walk and player-stays-above-ground. The ordinary worker completed the unchanged comparison as
needs-review: the engine passed, but frame 111 had no exact recorded answer. No live model ran.
The real CLI comparison also completed needs-review (exit 2), with exactly the same input
digests and missing request as the app. This machine cannot nest the replay sandbox; these real runs are diagnostic, not isolated.

The missing request is segment-at, point (488, 329), viewport 530x495. The old recorded PNG hash
is e68ce38322a6e75dccf8114263e7b6585c30fe149f1e083f2a979503572454b0; the newly replayed PNG hash
is 5c5df8b07348466a7df9ba1d9112e1efe71071c43dbd5274ae3ff64bb8fa047b. Only frame 111 differs out
of 180 frames. Two pixels differ, at (220,318) and (215,324), away from the queried player point.
The original capture has the same point prompt for its old PNG. This is not an extra app question:
the new image bytes were never recorded. Both PNGs and a standard-library regression test are in
the PR; the handover has the full real replay and app evidence.

## Not done

No unchanged-game accept is claimed from the current recording. Sean must decide whether to
record the exact new image/question above; no image tolerance, substituted answer or live fallback
was introduced. No recording, calibration, gate/verify.py, anchored.py or workflow was edited.
No new live recording, paid model, commit, push or GitHub write. The non-developer first-user test,
native macOS and Windows app checks remain open. Automated browser use is not that human test.

## Files

- contracts/verify-request.v1.schema.json
- contracts/examples/project-recorded.json
- contracts/examples/verify-request-recorded.json
- expectrail/project_job.py
- expectrail/app.py
- expectrail/app_kinematic.py
- expectrail/app_page.py
- expectrail/orchestrator/cli.py
- expectrail/orchestrator/engines.py
- expectrail/orchestrator/request.py
- setup.py
- tests/test_app.py
- tests/test_app_projects.py
- tests/fixtures/recorded-pixel-mismatch/recorded.png
- tests/fixtures/recorded-pixel-mismatch/replayed.png
- tests/fixtures/recorded-pixel-mismatch/question.json
- tests/fixtures/recorded-pixel-mismatch/README.md
- docs/app.md
- docs/project-config.md
- docs/new-work/2026-11-15-app-any-project.md
