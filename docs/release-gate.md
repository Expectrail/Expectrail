# Release gate

One control per row (#258). Each row's tests start real processes (the `expectrail verify` command, its
worker, Godot) and assert that clearance is **not** granted: that the command does not exit 0 and the
job is not an accept, or, on the two-job pull-request gate (#254), that the head's clearance check is
not a success. A row is held only when its tests ran and passed. A row without a test, or with a probe
that shows the control is not defended, is open, with the reason.

This file is written by `python3 -m tools.release_gate` from the results of one run. Do not edit it by
hand.

- Run: a local run, not CI
- Commit: `522ac07f25a71d1dcf58efc71b46260bf86d991e`
- When: 2026-11-15 22:18 UTC
- Rows: 35. Held 21, open 9, failed 0, not run 5.
- Positive controls (the same command clears the unchanged game and rejects the seeded bug; with a stand-in vision provider that answers, the live visual observer's path clears the unchanged game; the pull-request gate's command clears the unchanged game declared an intended change): passed.
- The two-job rows' own positive controls (the trusted judge clears the unchanged game's capture and rejects the seeded bug's): not run, so those rows are not run.
- The receipt rows' own positive control (the receipt verifier clears the receipt made from the unchanged game's job, asked about that job's own digests): passed.

## Identity and authority

| Control | Status | Why |
| --- | --- | --- |
| wrong build or head | held | 4 real-process tests passed. Covers the receipt verifier (`python3 -m expectrail.receipt trust-check`) run as its own process. The receipts are made by the test from real `expectrail verify` jobs with Godot (their head tree, request and policy digests and their decision) and signed with a key made in the test, because the trusted job writes no receipt yet (#255). The receipt writer and CI attestation are not covered |
| unknown signer | held | 5 real-process tests passed. Covers the receipt verifier (`python3 -m expectrail.receipt trust-check`) run as its own process. The receipts are made by the test from real `expectrail verify` jobs with Godot (their head tree, request and policy digests and their decision) and signed with a key made in the test, because the trusted job writes no receipt yet (#255). The receipt writer and CI attestation are not covered |
| swapped policy | held | 3 real-process tests passed |
| expired receipt | held | 4 real-process tests passed. Covers the receipt verifier (`python3 -m expectrail.receipt trust-check`) run as its own process. The receipts are made by the test from real `expectrail verify` jobs with Godot (their head tree, request and policy digests and their decision) and signed with a key made in the test, because the trusted job writes no receipt yet (#255). The receipt writer and CI attestation are not covered |
| changed head | not run | a test was skipped: the capture needs the replay sandbox, which cannot run here (bubblewrap (bwrap) is not installed) |
| an approval added by the change | held | 1 real-process test passed |

## Candidate interference

| Control | Status | Why |
| --- | --- | --- |
| writes to evidence or policy | not run | a test was skipped: the capture needs the replay sandbox, which cannot run here (bubblewrap (bwrap) is not installed) |
| a forged trace | open | undefended: since #254 the judgment runs outside the candidate job, but the game still runs in the Godot process that writes the trace, inside the capture's sandbox, so it can write a trace that is not what happened. A capture the game cannot forge is #246 and #273 |
| a rewritten frame | open | undefended: the game draws the frames the visual observer reads, and no capture the game cannot forge exists yet (#246, #273). The positive control asserts the run's grade is `diagnostic`, never `protected` |
| a poisoned import cache | held | 3 real-process tests passed. Covers the cache a change carries in its checkout; a run without the replay sandbox can still write the verifier's own cache, which the first test shows would change what is drawn |
| reading a private path | not run | a test was skipped: the replay sandbox cannot run here (bubblewrap (bwrap) is not installed); see `expectrail doctor --isolated` |
| network egress | not run | a test was skipped: the replay sandbox cannot run here (bubblewrap (bwrap) is not installed); see `expectrail doctor --isolated` |

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
| unreachable route | held | 2 real-process tests passed |
| zero evaluations | held | 1 real-process test passed |
| skipped required observer | held | 1 real-process test passed |
| missing private suite | held | 1 real-process test passed |

## Intent

| Control | Status | Why |
| --- | --- | --- |
| an approved intentional change passes as a contract change | held | 2 real-process tests passed. Covers the pull-request gate's command, which reads the declared intent; the orchestrator's command takes no intent and judges every change as undeclared. The positive side, a contract change approved and merged first and the behaviour after it, is not run: the recorded vision answers cover only the samples' frames and checks |
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
| disk quota | not run | a test was skipped: the replay sandbox cannot run here (bubblewrap (bwrap) is not installed); see `expectrail doctor --isolated` |
| provider outage | held | 1 real-process test passed |
| budget exhausted | held | 3 real-process tests passed |

## Tests

| Test | Result | Seconds |
| --- | --- | --- |
| `gate_bundle.BundleBaselineTest.test_the_trusted_judge_clears_the_unchanged_games_capture` | skipped | 0.0 |
| `gate_bundle.BundleBaselineTest.test_the_trusted_judge_rejects_the_seeded_bugs_capture` | skipped | 0.0 |
| `gate_bundle.EvidenceTest.test_a_capture_made_with_other_checks_is_refused` | skipped | 0.0 |
| `gate_bundle.EvidenceTest.test_a_frame_rewritten_between_the_jobs_is_refused` | skipped | 0.0 |
| `gate_bundle.EvidenceTest.test_a_run_taken_out_between_the_jobs_is_refused` | skipped | 0.0 |
| `gate_bundle.EvidenceTest.test_a_trace_and_its_replay_record_rewritten_together_are_refused_by_the_manifest` | skipped | 0.0 |
| `gate_bundle.EvidenceTest.test_a_trace_rewritten_between_the_jobs_is_refused` | skipped | 0.0 |
| `gate_bundle.EvidenceTest.test_an_intact_capture_from_a_different_base_game_is_refused` | skipped | 0.0 |
| `gate_bundle.EvidenceTest.test_an_intact_capture_from_a_different_head_game_is_refused` | skipped | 0.0 |
| `gate_bundle.EvidenceTest.test_checks_the_change_rewrites_are_not_the_ones_that_judge_it` | skipped | 0.0 |
| `gate_bundle.HeadTest.test_a_capture_made_for_the_old_head_is_refused_for_the_new_one` | skipped | 0.0 |
| `gate_bundle.HeadTest.test_a_new_head_pushed_before_the_judge_finished_is_not_given_clearance` | skipped | 0.0 |
| `gate_bundle.HeadTest.test_a_newer_attempt_of_the_candidate_run_takes_clearance_from_this_one` | skipped | 0.0 |
| `gate_bundle.HeadTest.test_control_the_head_that_was_judged_is_given_clearance` | skipped | 0.0 |
| `gate_coverage.CoverageTest.test_a_route_pattern_that_matches_no_file_is_not_clearance` | passed | 0.9 |
| `gate_coverage.CoverageTest.test_a_route_whose_inputs_the_game_does_not_have_is_not_clearance` | passed | 22.5 |
| `gate_coverage.CoverageTest.test_held_out_routes_that_cannot_be_read_are_not_clearance` | passed | 34.4 |
| `gate_coverage.CoverageTest.test_no_approved_spec_at_all_is_not_clearance` | passed | 1.0 |
| `gate_coverage.CoverageTest.test_specs_that_are_all_drafts_judge_nothing_and_are_not_clearance` | passed | 1.0 |
| `gate_coverage.CoverageTest.test_under_two_observers_a_missing_visual_observer_is_not_clearance` | passed | 34.0 |
| `gate_identity.IdentityTest.test_an_approval_the_change_adds_to_its_own_checks_judges_nothing` | passed | 36.6 |
| `gate_identity.IdentityTest.test_checks_swapped_and_put_back_exactly_are_the_checks_that_were_named` | passed | 17.7 |
| `gate_identity.IdentityTest.test_checks_swapped_between_the_request_and_the_run_judge_nothing` | passed | 0.4 |
| `gate_identity.IdentityTest.test_the_base_checks_swapped_after_the_request_judge_nothing` | passed | 0.5 |
| `gate_intent.IntentBaselineTest.test_the_pull_request_gate_clears_the_unchanged_game_declared_an_intended_change` | passed | 33.3 |
| `gate_intent.IntentTest.test_a_change_declared_intended_that_breaks_an_approved_check_is_rejected` | passed | 41.6 |
| `gate_intent.IntentTest.test_a_change_declared_intended_that_rewrites_the_check_it_breaks_is_judged_by_the_approved_check` | passed | 42.7 |
| `gate_intent.IntentTest.test_a_generated_block_that_cannot_be_read_changes_nothing` | passed | 41.4 |
| `gate_intent.IntentTest.test_a_tolerance_the_change_weakens_in_its_own_check_is_not_the_one_that_judges_it` | passed | 41.9 |
| `gate_intent.IntentTest.test_generated_checks_that_caught_nothing_do_not_clear_a_change_an_approved_check_rejects` | passed | 41.8 |
| `gate_interference.ImportCacheTest.test_a_broken_change_that_carries_an_import_cache_is_still_rejected` | passed | 43.1 |
| `gate_interference.ImportCacheTest.test_an_import_cache_the_change_carries_is_never_drawn_from` | passed | 17.7 |
| `gate_interference.ImportCacheTest.test_control_the_same_poison_in_the_verifiers_own_cache_changes_what_is_drawn` | passed | 17.4 |
| `gate_operations.BaselineTest.test_the_unchanged_game_is_cleared_through_the_same_command` | passed | 61.3 |
| `gate_operations.OperationsTest.test_a_cancelled_job_is_not_clearance_and_leaves_nothing_running` | passed | 2.3 |
| `gate_operations.OperationsTest.test_a_job_that_runs_out_of_time_is_not_clearance_and_leaves_nothing_running` | passed | 3.4 |
| `gate_operations.OperationsTest.test_a_key_used_for_one_change_does_not_clear_another` | passed | 17.6 |
| `gate_operations.OperationsTest.test_a_killed_worker_is_not_clearance_and_leaves_nothing_running` | passed | 1.3 |
| `gate_operations.OperationsTest.test_asking_again_after_a_lost_worker_returns_the_failure_not_a_new_verdict` | passed | 1.4 |
| `gate_operations.OperationsTest.test_the_same_request_twice_at_once_is_one_job_with_one_verdict` | passed | 42.7 |
| `gate_provider.ProviderBaselineTest.test_with_the_provider_answering_the_live_observer_clears_the_unchanged_game` | passed | 18.3 |
| `gate_provider.ProviderTest.test_a_cap_of_nothing_sends_nothing_and_is_not_clearance` | passed | 17.5 |
| `gate_provider.ProviderTest.test_a_cap_spent_part_way_stops_the_requests_and_is_not_clearance` | passed | 18.2 |
| `gate_provider.ProviderTest.test_a_provider_out_of_credit_is_not_clearance` | passed | 18.1 |
| `gate_provider.ProviderTest.test_a_provider_outage_is_not_clearance_and_does_not_hide_a_broken_build` | passed | 129.5 |
| `gate_receipt.ReceiptTest.test_a_head_or_build_left_unasked_is_not_a_pass` | passed | 0.3 |
| `gate_receipt.ReceiptTest.test_a_receipt_carrying_the_trusted_key_but_signed_by_another_is_not_cleared` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_receipt_for_another_repository_does_not_clear_this_one` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_receipt_for_one_build_of_a_head_does_not_clear_another_build_of_it` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_receipt_issued_in_the_future_is_not_cleared` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_receipt_naming_the_trusted_key_id_with_another_key_is_not_cleared` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_receipt_past_its_expiry_is_not_cleared` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_receipt_signed_by_a_key_the_store_does_not_hold_is_not_cleared` | passed | 0.2 |
| `gate_receipt.ReceiptTest.test_a_receipt_valid_for_longer_than_seven_days_is_not_cleared` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_a_store_without_the_signers_key_clears_nothing` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_an_expired_receipt_with_its_dates_edited_after_signing_is_not_cleared` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_control_the_unchanged_games_receipt_is_cleared_for_that_job` | passed | 0.1 |
| `gate_receipt.ReceiptTest.test_the_seeded_bugs_reject_edited_to_accept_after_signing_is_not_cleared` | passed | 0.2 |
| `gate_receipt.ReceiptTest.test_the_unchanged_games_receipt_does_not_clear_the_seeded_bugs_head` | passed | 0.1 |
| `gate_sandbox.DiskQuotaTest.test_control_without_the_sandbox_a_change_that_fills_the_disk_writes_it_all_and_is_cleared` | skipped | 0.0 |
| `gate_sandbox.DiskQuotaTest.test_in_the_isolated_class_a_change_that_fills_the_disk_is_stopped_and_not_cleared` | skipped | 0.0 |
| `gate_sandbox.EgressTest.test_control_without_the_sandbox_a_change_that_reaches_a_port_is_cleared` | skipped | 0.0 |
| `gate_sandbox.EgressTest.test_in_the_isolated_class_a_change_cannot_reach_a_port_and_is_rejected` | skipped | 0.0 |
| `gate_sandbox.PrivatePathTest.test_control_without_the_sandbox_a_change_that_reads_a_private_file_is_cleared` | skipped | 0.0 |
| `gate_sandbox.PrivatePathTest.test_in_the_isolated_class_a_change_cannot_read_a_private_file_and_is_rejected` | skipped | 0.0 |
| `gate_sandbox.PrivatePathTest.test_the_isolated_class_clears_the_unchanged_game` | skipped | 0.0 |
