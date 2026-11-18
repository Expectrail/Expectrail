# Release gate

One control per row (#258). Each row's tests start real processes (the `expectrail verify` command, its
worker, Godot) and assert that clearance is **not** granted: that the command does not exit 0 and the
job is not an accept, or, on the two-job pull-request gate (#254), that the head's clearance check is
not a success. A row is held only when its tests ran and passed. A row without a test, or with a probe
that shows the control is not defended, is open, with the reason.

This file is written by `python3 -m tools.release_gate` from the results of one run. Do not edit it by
hand.

- Run: [CI run 43817779257](https://github.com/Expectrail/Expectrail/actions/runs/43817779257)
- Commit: `12434136b8f240c98df4015720a585d84c02320a`
- When: 2026-11-16 06:51 UTC
- Rows: 35. Held 25, open 10, failed 0, not run 0.
- Positive controls (the same command clears the unchanged game and rejects the seeded bug; with a stand-in vision provider that answers, the live visual observer's path clears the unchanged game; the pull-request gate's command clears the unchanged game declared an intended change): passed.
- The two-job rows' own positive controls (the trusted judge clears the unchanged game's capture and rejects the seeded bug's): passed.
- The receipt rows' own positive control (the receipt verifier clears the receipt made from the unchanged game's job, asked about that job's own digests): passed.

## Identity and authority

| Control | Status | Why |
| --- | --- | --- |
| wrong build or head | held | 4 real-process tests passed. Covers the receipt verifier (`python3 -m expectrail.receipt trust-check`) run as its own process. The receipts are made by the test from real `expectrail verify` jobs with Godot (their head tree, request and policy digests and their decision) and signed with a key made in the test, because the trusted job writes no receipt yet (#255). The receipt writer and CI attestation are not covered |
| unknown signer | held | 5 real-process tests passed. Covers the receipt verifier (`python3 -m expectrail.receipt trust-check`) run as its own process. The receipts are made by the test from real `expectrail verify` jobs with Godot (their head tree, request and policy digests and their decision) and signed with a key made in the test, because the trusted job writes no receipt yet (#255). The receipt writer and CI attestation are not covered |
| swapped policy | held | 3 real-process tests passed |
| expired receipt | held | 4 real-process tests passed. Covers the receipt verifier (`python3 -m expectrail.receipt trust-check`) run as its own process. The receipts are made by the test from real `expectrail verify` jobs with Godot (their head tree, request and policy digests and their decision) and signed with a key made in the test, because the trusted job writes no receipt yet (#255). The receipt writer and CI attestation are not covered |
| changed head | held | 4 real-process tests passed. Covers the two-job gate (#254): the capture and the trusted judge run as real processes with Godot in the replay sandbox, and the trusted job's step that completes the head checks runs against a stand-in for GitHub's API. The hosted run on a test pull request is not part of this suite |
| an approval added by the change | held | 1 real-process test passed |

## Candidate interference

| Control | Status | Why |
| --- | --- | --- |
| writes to evidence or policy | held | 8 real-process tests passed. Covers the two-job gate (#254): edits between the jobs, an archive consistent in itself whose recorded base or head game tree differs from its checkout, and checks the change carries. The artifact download needs GitHub and is not run here. What the game itself writes from inside its replay is the forged-trace and rewritten-frame rows |
| a forged trace | open | undefended: since #254 the judgment runs outside the candidate job, but the game still runs in the Godot process that writes the trace, inside the capture's sandbox, so it can write a trace that is not what happened. A capture the game cannot forge is #246 and #273 |
| a rewritten frame | open | undefended: the game draws the frames the visual observer reads, and no capture the game cannot forge exists yet (#246, #273). The positive control asserts the run's grade is `diagnostic`, never `protected` |
| a poisoned import cache | held | 3 real-process tests passed. Covers the cache a change carries in its checkout; a run without the replay sandbox can still write the verifier's own cache, which the first test shows would change what is drawn |
| reading a private path | held | 3 real-process tests passed. Covers the isolated class (`--execution-class isolated`), where every replay is in the sandbox. The default class sandboxes only where the machine can; without the sandbox the first test shows a broken change that reads a file outside its checkout repairing itself and being cleared |
| network egress | held | 2 real-process tests passed. Covers the isolated class, as above; the port is on this machine's loopback, the nearest address a change could reach. Without the sandbox the first test shows a broken change that reaches it repairing itself and being cleared |

## Observation

| Control | Status | Why |
| --- | --- | --- |
| dropped frames | open | not written yet: it needs the observation timeline (#257) |
| duplicated frames | open | equal-count repeated or stale content is not authenticated by the current game-origin capture (#257, #246); refusing an extra frame alone does not defend the complete control |
| out-of-order frames | open | not written yet: it needs the observation timeline (#257) |
| tick phase error | open | not written yet: it needs the observation timeline (#257) |
| resolution change | open | the complete resolution/timeline control is not demonstrated (#257): independent capture geometry and tick binding are absent; only intra-replay PNG dimension changes are refused |
| two same-class targets | open | not written yet: it needs the observation timeline (#257) |
| occlusion | open | not written yet: it needs the observation timeline (#257) |

## Coverage

| Control | Status | Why |
| --- | --- | --- |
| empty suite | held | 1 real-process test passed |
| unreachable route | held | 2 real-process tests passed |
| zero evaluations | held | 1 real-process test passed |
| skipped required observer | held | 1 real-process test passed |
| missing private suite | held | 1 real-process test passed |

## Intent

| Control | Status | Why |
| --- | --- | --- |
| an approved intentional change passes as a contract change | open | positive contract-change case is not run: it needs a person's approval of the changed contract and matching recorded visual evidence. The negative controls alone do not prove it |
| a weakened tolerance | held | 1 real-process test passed. Covers runs with a base, where the checks come from the base. Without a base a change's own checks judge it, and nothing yet binds an approval to the check's content (#420); such a run is needs-review in this suite only because the recorded answers do not cover the edited check |
| a misleading generated check stays advisory | held | 2 real-process tests passed. Covers the pull-request gate's command, the only one that reads a generated block; the orchestrator's command never reads one |

## Operations

| Control | Status | Why |
| --- | --- | --- |
| timeout | held | 1 real-process test passed |
| cancellation | held | 1 real-process test passed |
| worker killed | held | 1 real-process test passed |
| retry | held | 1 real-process test passed |
| duplicate request | held | 2 real-process tests passed |
| disk quota | held | 2 real-process tests passed. Covers the replay sandbox's bound on what a replay adds to its work copy and output folder (4 GiB and 250,000 files by default, lowered to 32 MB here), measured every 0.1 s and after the replay ends, so a game can pass it by what the disk takes in 0.1 s before it is stopped. Without the sandbox the first test shows the same change writing all 96 MB and being cleared. Bounded only where the replay runs in the sandbox (the isolated class); the import cache the verifier keeps between jobs and the job's own files outside the replay are not bounded by it |
| provider outage | held | 1 real-process test passed |
| budget exhausted | held | 3 real-process tests passed |

## Tests

| Test | Result | Seconds |
| --- | --- | --- |
| `gate_bundle.BundleBaselineTest.test_the_trusted_judge_clears_the_unchanged_games_capture` | passed | 1.3 |
| `gate_bundle.BundleBaselineTest.test_the_trusted_judge_rejects_the_seeded_bugs_capture` | passed | 1.0 |
| `gate_bundle.EvidenceTest.test_a_capture_made_with_other_checks_is_refused` | passed | 0.2 |
| `gate_bundle.EvidenceTest.test_a_frame_rewritten_between_the_jobs_is_refused` | passed | 0.8 |
| `gate_bundle.EvidenceTest.test_a_resolution_change_with_consistent_manifest_is_refused` | passed | 0.9 |
| `gate_bundle.EvidenceTest.test_a_run_taken_out_between_the_jobs_is_refused` | passed | 0.2 |
| `gate_bundle.EvidenceTest.test_a_trace_and_its_replay_record_rewritten_together_are_refused_by_the_manifest` | passed | 0.9 |
| `gate_bundle.EvidenceTest.test_a_trace_rewritten_between_the_jobs_is_refused` | passed | 0.5 |
| `gate_bundle.EvidenceTest.test_an_extra_frame_with_consistent_manifest_is_refused` | passed | 0.9 |
| `gate_bundle.EvidenceTest.test_an_intact_capture_from_a_different_base_game_is_refused` | passed | 0.5 |
| `gate_bundle.EvidenceTest.test_an_intact_capture_from_a_different_head_game_is_refused` | passed | 0.8 |
| `gate_bundle.EvidenceTest.test_checks_the_change_rewrites_are_not_the_ones_that_judge_it` | passed | 32.7 |
| `gate_bundle.HeadTest.test_a_capture_made_for_the_old_head_is_refused_for_the_new_one` | passed | 1.1 |
| `gate_bundle.HeadTest.test_a_new_head_pushed_before_the_judge_finished_is_not_given_clearance` | passed | 1.0 |
| `gate_bundle.HeadTest.test_a_newer_attempt_of_the_candidate_run_takes_clearance_from_this_one` | passed | 1.0 |
| `gate_bundle.HeadTest.test_control_the_head_that_was_judged_is_given_clearance` | passed | 1.0 |
| `gate_coverage.CoverageTest.test_a_route_pattern_that_matches_no_file_is_not_clearance` | passed | 0.7 |
| `gate_coverage.CoverageTest.test_a_route_whose_inputs_the_game_does_not_have_is_not_clearance` | passed | 16.0 |
| `gate_coverage.CoverageTest.test_held_out_routes_that_cannot_be_read_are_not_clearance` | passed | 23.8 |
| `gate_coverage.CoverageTest.test_no_approved_spec_at_all_is_not_clearance` | passed | 0.7 |
| `gate_coverage.CoverageTest.test_specs_that_are_all_drafts_judge_nothing_and_are_not_clearance` | passed | 0.7 |
| `gate_coverage.CoverageTest.test_under_two_observers_a_missing_visual_observer_is_not_clearance` | passed | 23.5 |
| `gate_identity.IdentityTest.test_an_approval_the_change_adds_to_its_own_checks_judges_nothing` | passed | 25.2 |
| `gate_identity.IdentityTest.test_checks_swapped_and_put_back_exactly_are_the_checks_that_were_named` | passed | 12.7 |
| `gate_identity.IdentityTest.test_checks_swapped_between_the_request_and_the_run_judge_nothing` | passed | 0.3 |
| `gate_identity.IdentityTest.test_the_base_checks_swapped_after_the_request_judge_nothing` | passed | 0.3 |
| `gate_intent.IntentBaselineTest.test_the_pull_request_gate_clears_the_unchanged_game_declared_an_intended_change` | passed | 23.8 |
| `gate_intent.IntentTest.test_a_change_declared_intended_that_breaks_an_approved_check_is_rejected` | passed | 30.9 |
| `gate_intent.IntentTest.test_a_change_declared_intended_that_rewrites_the_check_it_breaks_is_judged_by_the_approved_check` | passed | 31.1 |
| `gate_intent.IntentTest.test_a_generated_block_that_cannot_be_read_changes_nothing` | passed | 31.0 |
| `gate_intent.IntentTest.test_a_tolerance_the_change_weakens_in_its_own_check_is_not_the_one_that_judges_it` | passed | 32.0 |
| `gate_intent.IntentTest.test_generated_checks_that_caught_nothing_do_not_clear_a_change_an_approved_check_rejects` | passed | 31.1 |
| `gate_interference.ImportCacheTest.test_a_broken_change_that_carries_an_import_cache_is_still_rejected` | passed | 31.6 |
| `gate_interference.ImportCacheTest.test_an_import_cache_the_change_carries_is_never_drawn_from` | passed | 12.6 |
| `gate_interference.ImportCacheTest.test_control_the_same_poison_in_the_verifiers_own_cache_changes_what_is_drawn` | passed | 12.4 |
| `gate_operations.BaselineTest.test_the_unchanged_game_is_cleared_through_the_same_command` | passed | 44.1 |
| `gate_operations.OperationsTest.test_a_cancelled_job_is_not_clearance_and_leaves_nothing_running` | passed | 0.4 |
| `gate_operations.OperationsTest.test_a_job_that_runs_out_of_time_is_not_clearance_and_leaves_nothing_running` | passed | 3.3 |
| `gate_operations.OperationsTest.test_a_key_used_for_one_change_does_not_clear_another` | passed | 12.7 |
| `gate_operations.OperationsTest.test_a_killed_worker_is_not_clearance_and_leaves_nothing_running` | passed | 1.4 |
| `gate_operations.OperationsTest.test_asking_again_after_a_lost_worker_returns_the_failure_not_a_new_verdict` | passed | 1.5 |
| `gate_operations.OperationsTest.test_the_same_request_twice_at_once_is_one_job_with_one_verdict` | passed | 31.6 |
| `gate_provider.ProviderBaselineTest.test_with_the_provider_answering_the_live_observer_clears_the_unchanged_game` | passed | 13.0 |
| `gate_provider.ProviderTest.test_a_cap_of_nothing_sends_nothing_and_is_not_clearance` | passed | 12.5 |
| `gate_provider.ProviderTest.test_a_cap_spent_part_way_stops_the_requests_and_is_not_clearance` | passed | 12.8 |
| `gate_provider.ProviderTest.test_a_provider_out_of_credit_is_not_clearance` | passed | 12.9 |
| `gate_provider.ProviderTest.test_a_provider_outage_is_not_clearance_and_does_not_hide_a_broken_build` | passed | 114.5 |
| `gate_receipt.ReceiptTest.test_a_head_or_build_left_unasked_is_not_a_pass` | passed | 0.2 |
| `gate_receipt.ReceiptTest.test_a_receipt_carrying_the_trusted_key_but_signed_by_another_is_not_cleared` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_receipt_for_another_repository_does_not_clear_this_one` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_receipt_for_one_build_of_a_head_does_not_clear_another_build_of_it` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_receipt_issued_in_the_future_is_not_cleared` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_receipt_naming_the_trusted_key_id_with_another_key_is_not_cleared` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_receipt_past_its_expiry_is_not_cleared` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_receipt_signed_by_a_key_the_store_does_not_hold_is_not_cleared` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_receipt_valid_for_longer_than_seven_days_is_not_cleared` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_store_without_the_signers_key_clears_nothing` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_an_expired_receipt_with_its_dates_edited_after_signing_is_not_cleared` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_control_the_unchanged_games_receipt_is_cleared_for_that_job` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_the_seeded_bugs_reject_edited_to_accept_after_signing_is_not_cleared` | passed | 0.2 |
| `gate_receipt.ReceiptTest.test_the_unchanged_games_receipt_does_not_clear_the_seeded_bugs_head` | passed | 0.1 |
| `gate_sandbox.DiskQuotaTest.test_control_without_the_sandbox_a_change_that_fills_the_disk_writes_it_all_and_is_cleared` | passed | 30.5 |
| `gate_sandbox.DiskQuotaTest.test_in_the_isolated_class_a_change_that_fills_the_disk_is_stopped_and_not_cleared` | passed | 20.7 |
| `gate_sandbox.EgressTest.test_control_without_the_sandbox_a_change_that_reaches_a_port_is_cleared` | passed | 29.0 |
| `gate_sandbox.EgressTest.test_in_the_isolated_class_a_change_cannot_reach_a_port_and_is_rejected` | passed | 32.0 |
| `gate_sandbox.PrivatePathTest.test_control_without_the_sandbox_a_change_that_reads_a_private_file_is_cleared` | passed | 28.9 |
| `gate_sandbox.PrivatePathTest.test_in_the_isolated_class_a_change_cannot_read_a_private_file_and_is_rejected` | passed | 31.7 |
| `gate_sandbox.PrivatePathTest.test_the_isolated_class_clears_the_unchanged_game` | passed | 24.3 |
