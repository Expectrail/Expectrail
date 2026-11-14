# Release gate

One control per row (#258). Each row's tests start real processes (the `expectrail verify` command, its
worker, Godot) and assert that clearance is **not** granted: today, that the command does not exit 0
and the job is not an accept. A row is held only when its tests ran and passed. A row without a test,
or with a probe that shows the control is not defended, is open, with the reason.

This file is written by `python3 -m tools.release_gate` from the results of one run. Do not edit it by
hand.

- Run: a local run, not CI
- Commit: `346f795b3d411773a71f3049f8f0fa8669b46448`
- When: 2026-11-14 07:13 UTC
- Rows: 35. Held 12, open 23, failed 0, not run 0.
- Positive controls (the same command clears the unchanged game and rejects the seeded bug; with a stand-in vision provider that answers, the live visual observer's path clears the unchanged game): passed.

## Identity and authority

| Control | Status | Why |
| --- | --- | --- |
| wrong build or head | open | not written yet: it needs the signed receipt (#255) |
| unknown signer | open | not written yet: it needs the signed receipt (#255) |
| swapped policy | open | not written yet in this suite (the orchestrator refuses checks that change after a job is created, tests/test_orchestrator.py, with a stand-in replay; a real-process test is the next slice) |
| expired receipt | open | not written yet: it needs the signed receipt (#255) |
| changed head | open | not written yet: it needs the trusted job that judges outside the candidate job (#254) |
| an approval added by the change | held | 1 real-process test passed |

## Candidate interference

| Control | Status | Why |
| --- | --- | --- |
| writes to evidence or policy | open | not written yet: it needs the trusted job that judges outside the candidate job (#254) |
| a forged trace | open | not written yet: it needs the trusted job that judges outside the candidate job (#254); until then the game writes the trace the gate reads, in the same job |
| a rewritten frame | open | undefended: the game draws the frames the visual observer reads, and no capture the game cannot forge exists yet (#246, #273). The positive control asserts the run's grade is `diagnostic`, never `protected` |
| a poisoned import cache | open | not written yet in this suite |
| reading a private path | open | not written yet in this suite (the replay sandbox's own tests cover it with bubblewrap: tests/test_replay_sandbox.py) |
| network egress | open | not written yet in this suite (the replay sandbox's own tests cover it with bubblewrap: tests/test_replay_sandbox.py) |

## Observation

| Control | Status | Why |
| --- | --- | --- |
| dropped frames | open | not written yet: it needs the observation timeline (#257) |
| duplicated frames | open | not written yet: it needs the observation timeline (#257) |
| out-of-order frames | open | not written yet: it needs the observation timeline (#257) |
| tick phase error | open | not written yet: it needs the observation timeline (#257) |
| resolution change | open | not written yet: it needs the observation timeline (#257) |
| two same-class targets | open | not written yet: it needs the observation timeline (#257) |
| occlusion | open | not written yet: it needs the observation timeline (#257) |

## Coverage

| Control | Status | Why |
| --- | --- | --- |
| empty suite | held | 1 real-process test passed |
| unreachable route | open | undefended: a route whose every input names an action the game does not have is replayed, the player stands still, and nothing says so (#417). On a590aac's engine-only path it was accepted; with both observers a live observer would see the robot above the ground. The probe, which asks that the job name the missing action, is an expected failure until then (probe run: it still fails, as expected) |
| zero evaluations | held | 1 real-process test passed |
| skipped required observer | held | 1 real-process test passed |
| missing private suite | held | 1 real-process test passed |

## Intent

| Control | Status | Why |
| --- | --- | --- |
| an approved intentional change passes as a contract change | open | not written yet in this suite |
| a weakened tolerance | open | not written yet in this suite |
| a misleading generated check stays advisory | open | not written yet in this suite |

## Operations

| Control | Status | Why |
| --- | --- | --- |
| timeout | held | 1 real-process test passed |
| cancellation | held | 1 real-process test passed |
| worker killed | held | 1 real-process test passed |
| retry | held | 1 real-process test passed |
| duplicate request | held | 2 real-process tests passed |
| disk quota | open | undefended: a replay's files are capped one by one, and nothing bounds a job's total disk use yet (#253) |
| provider outage | held | 1 real-process test passed |
| budget exhausted | held | 3 real-process tests passed |

## Tests

| Test | Result | Seconds |
| --- | --- | --- |
| `gate_coverage.CoverageTest.test_a_route_pattern_that_matches_no_file_is_not_clearance` | passed | 0.9 |
| `gate_coverage.CoverageTest.test_a_route_whose_inputs_the_game_does_not_have_is_not_clearance` | expected failure | 25.1 |
| `gate_coverage.CoverageTest.test_held_out_routes_that_cannot_be_read_are_not_clearance` | passed | 40.3 |
| `gate_coverage.CoverageTest.test_no_approved_spec_at_all_is_not_clearance` | passed | 1.0 |
| `gate_coverage.CoverageTest.test_specs_that_are_all_drafts_judge_nothing_and_are_not_clearance` | passed | 0.9 |
| `gate_coverage.CoverageTest.test_under_two_observers_a_missing_visual_observer_is_not_clearance` | passed | 39.9 |
| `gate_identity.IdentityTest.test_an_approval_the_change_adds_to_its_own_checks_judges_nothing` | passed | 44.8 |
| `gate_operations.BaselineTest.test_the_unchanged_game_is_cleared_through_the_same_command` | passed | 75.8 |
| `gate_operations.OperationsTest.test_a_cancelled_job_is_not_clearance_and_leaves_nothing_running` | passed | 1.6 |
| `gate_operations.OperationsTest.test_a_job_that_runs_out_of_time_is_not_clearance_and_leaves_nothing_running` | passed | 3.4 |
| `gate_operations.OperationsTest.test_a_key_used_for_one_change_does_not_clear_another` | passed | 22.0 |
| `gate_operations.OperationsTest.test_a_killed_worker_is_not_clearance_and_leaves_nothing_running` | passed | 1.3 |
| `gate_operations.OperationsTest.test_asking_again_after_a_lost_worker_returns_the_failure_not_a_new_verdict` | passed | 1.6 |
| `gate_operations.OperationsTest.test_the_same_request_twice_at_once_is_one_job_with_one_verdict` | passed | 53.3 |
| `gate_provider.ProviderBaselineTest.test_with_the_provider_answering_the_live_observer_clears_the_unchanged_game` | passed | 24.2 |
| `gate_provider.ProviderTest.test_a_cap_of_nothing_sends_nothing_and_is_not_clearance` | passed | 24.6 |
| `gate_provider.ProviderTest.test_a_cap_spent_part_way_stops_the_requests_and_is_not_clearance` | passed | 23.9 |
| `gate_provider.ProviderTest.test_a_provider_out_of_credit_is_not_clearance` | passed | 22.2 |
| `gate_provider.ProviderTest.test_a_provider_outage_is_not_clearance_and_does_not_hide_a_broken_build` | passed | 145.6 |
