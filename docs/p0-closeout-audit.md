# Five P0 close-out checks

Audited main **ec0919b60c03abf033ef79a996880300658e6887**, November 16, 2026.
The five issues' original Build, rules and Done when text were read in full.
This is an inventory of evidence and remaining work, not a new acceptance rule.
Test names below are Python unittest names. A stand-in passing is distinguished
from a real replay, a live model run and a first-user trial.

**Close #422 and #329. Keep #433, #370 and #420 open.** The last three still
have explicit unmet cases. No live call, approval, workflow change, dispatch,
push or GitHub comment was made in this audit.

The supplied branch is at that main pin. #548, #551, #555, #502, #516 and #568
are merged there. #559 and #570 are still open when checked; their menu/pointer
and later Breakout claims are not counted as evidence on main. They are also
not new requirements for the narrower original input-map issue #329.

## #433 — reject, then fix

Scope: [issue #433](https://github.com/Expectrail/Expectrail/issues/433), including
its four safety rules, four slices and bundled fall-through Done when.
**Part of #433**: the offline command path is tested; the literal live
repair/auto-fix case, published fourth sample and CI draft-PR slice remain.

| Case | Evidence on main, or missing |
| --- | --- |
| Verify rejects the seeded fall-through, then repair gets a fresh accept with repair demonstrated | `tests.test_repair_command.RepairCommandTest.test_fixture_accepts_only_after_fresh_fix_verification`: copies the bundled bug/fixture patch, uses stand-in replays/vision, asserts a new child job and `repair.demonstrated > 0`. This is offline command proof, not a real-engine CI repair run. |
| `--auto-fix` takes a reject through that path without replacing the original verdict | `tests.test_auto_fix.AutoFixTest.test_accept_on_candidate_leaves_original_rejected_and_retry_reuses_record`: fresh child accepts, parent stays reject, retry reuses the record. Stand-in observers. |
| A bounded fixer can be selected from `repair JOB` | **Gap fixed here:** `tests.test_p0_closeout.RepairAgentCommandTest.test_explicit_llm_patch_reaches_existing_fixer_and_fresh_gate`. `--agent llm-patch` now forwards to the existing function/loop. The test supplies a fixture patch, records source `fixture`, and proves no model-quality claim. Unknown choices are refused with no fixer call. All existing caps remain. |
| Fixer is independent; receives only public failing sentences, not policy internals or vision | `tests.test_repair_command.RepairCommandTest.test_game_embedded_checks_and_vision_recording_never_reach_fixer`; `test_each_rejection_retries_from_original_and_gets_only_public_feedback`. Actual fixture source is correctly labelled unsandboxed. Live sandbox enforcement belongs to the existing fixer and budget path, not this test. |
| No held-out material in fixer/retry evidence | `tests.test_ingest_repair.IngestRepair.test_heldout_only_veto_retry_contains_only_public_failures` exercises a synthetic held-out veto; no private material is used. **Missing integration:** `expectrail.repair.repair` refuses an original job with `heldOut.status != not-used`; it cannot currently reproduce such a job's held-out routes in a public child request. Safety refusal is not evidence that this full slice is implemented. |
| Every candidate verified independently with the original policy | `tests.test_repair_command.RepairCommandTest.test_fixture_accepts_only_after_fresh_fix_verification`, `test_refuses_changed_policy_missing_live_cap_and_invalid_attempts`; `expectrail.repair._child` pins policy/head digests and intent `fix`. Held-out integration limitation above still applies. |
| Stop at accept or needs-review; never retry a review into accept | `tests.test_repair_command.RepairCommandTest.test_no_visual_answer_stops_at_needs_review`; `tests.test_ingest_repair.IngestRepair.test_advisory_flag_stops_after_candidate_gate_accept_or_reject`. |
| Never-successful fixer exhausts attempts, records all attempts, ends needs-review | `tests.test_repair_command.RepairCommandTest.test_each_rejection_retries_from_original_and_gets_only_public_feedback`; `tests.test_auto_fix.AutoFixTest.test_recorded_candidate_exhausts_attempts`. Two distinct rejected child jobs, no winning patch. |
| Spend stop is review, with enforced bounds and no send past cap | `tests.test_live_repair_kit.RecordedRealRehearsal.test_real_mid_run_budget_stop_no_candidate_or_retry` reads the [real-engine localhost rehearsal](live-repair/rehearsal.json); `tests.test_live_repair_kit.CurrentModel.test_usage_violation_prevents_later_send` exercises the provider stand-in. These are not paid-provider measurements. |
| Machine-written label in job, record, report, viewer and app; original checkout unchanged | `tests.test_repair_command.RepairCommandTest.test_viewer_reads_the_record_and_patch_written_by_fixture_repair`; `tests.test_auto_fix.AutoFixTest.test_app_reject_summary_links_only_the_owned_repair_and_shows_review`; the first command test asserts unchanged source bytes. |
| No automatic merge | Repair returns a candidate patch plus review label; the tests above assert the original remains unchanged. `tests.test_ci_autofix.WorkflowTest.test_only_the_label_can_schedule_a_read_only_fixture` checks artifact-only/read-only CI. No merge implementation is present in these paths. This is source/offline evidence, not a hosted end-to-end merge-control trial. |
| App auto-fix setting shows attempt limit and cap before launch | `tests.test_auto_fix.AutoFixTest.test_app_requires_explicit_cap_and_attempt_limit_before_launch`. **Limitation:** app/verify auto-fix still selects Muse; the new direct repair selector does not change it. The unbounded Muse CLI stays refused with `fixer-bound-unavailable`. |
| Real Godot reproduction through ingest | #551: `tests.test_replay_sandbox.PlaytestIngestRealEngineTest.test_approved_ground_check_reproduces_three_times`. This proves intake reproduction, not a repair. #548 adds the opt-in repair wiring. |
| Real-engine end-to-end repair rehearsal | #568: [rehearsal](live-repair/rehearsal.json), checked by `tests.test_live_repair_kit.RecordedRealRehearsal.test_real_accepted_repair_by_both_observers` and `test_real_candidate_rejected_by_the_gate`. Real CLI/Godot/Bubblewrap, localhost stand-ins, zero live calls. It uses **ingest --repair**, not the literal verify/repair/auto-fix live Done when. |
| Offline fixture repair through literal commands in CI, and once live | **Missing complete recorded case:** the command tests are stand-in replays; the real-engine rehearsal is ingest. Existing `expectrail-autofix.yml` and `tests.test_ci_autofix` prepare fixture CI, but no hosted full literal-command run is cited as done. **Missing live repair and live auto-fix:** no model-quality outcome exists. |
| Fourth Run it sample shows a recorded fixer repair on expectrail.tech | **Missing.** [samples.json](run-it/samples.json) has `recorded-fix.repairRecorded: false`; the card is deliberately disabled. `tests.test_visible_repair.RepairTest.test_unpublished_sample_never_reads_even_an_available_record` proves refusal, not publication. Timeline/diff rendering is tested by `test_full_diff_is_escaped_in_both_pages_and_fixture_is_identified`. |
| A future llm-patch live record can populate that fourth sample | **Missing reader compatibility.** `expectrail.runit` requires `fixer.sandboxed: true`; the existing llm-patch repair writer honestly records false because no sandboxed agent process ran. Even a successful live kit result cannot simply be published by flipping a flag. A reviewed provenance/safety decision and compatible reader/test are required; never relabel the record as sandboxed. |
| Opt-in CI draft PR after reject | **Missing draft-PR publication.** [CI fixture handover](new-work/2026-11-14-ci-fixture-repair.md) and `tests.test_ci_autofix` cover a labelled, same-head, read-only fixture/artifact path. A workflow that creates a draft PR is Sean's separate reviewed step, not an existing capability. |

### Exact next steps for #433

1. **Builder follow-up before Sean can claim the literal auto-fix live case:**
   decide and wire an explicitly bounded agent through auto-fix's request contract,
   worker and app. Currently `auto_fix.configure` writes source `muse` and the worker
   has no llm-patch selection. Do not remove the Muse refusal or rely on a CLI soft
   cap. This changes the request producer/reader and is beyond the two small fixes.
   Add the missing real-engine literal verify → repair and verify → auto-fix CI
   evidence, using fixtures/recorded vision without secrets. Also design the
   trusted held-out child-request path if that broader safety slice is to close.
2. **Sean, optional narrower live ingest measurement:** review/install the
   [proposed workflow](proposals/531-live-repair-workflow.md), provision its runner,
   keys and persistent month ledgers exactly as [the run sheet](live-repair/RUN-SHEET.md)
   states, then dispatch **One public live repair** once on **main**, one attempt,
   recommended caps, `confirm=true`. It is a proposal, not an installed workflow.
   The authorized cap sum is $10 (fixer $6 plus two $2 vision envelopes); the
   tighter request-admission envelope is $9.842584 at the recorded tariff. Confirm
   the tariff/model review is still current first. Do not run it just to close
   this audit. This is one report/bug/model, not a repair rate or the auto-fix case.
3. **Sean, resolve the sample's fixer-provenance policy first:** the current
   sample accepts only a live sandboxed fixer record, while the bounded kit uses
   a provider-only llm-patch writer and records `sandboxed: false`. Either obtain
   an enforceably bounded sandboxed-agent recording, or explicitly review and
   build the sample reader's support for provider-only provenance with tests.
   Do not change the record to bypass that distinction. Once compatible genuine
   repair evidence exists, follow [Run it publishing](run-it.md).
   Preserve the real repair-run, winning patch/digest and saved vision answers;
   make the dedicated recording name `recorded-fix`, put the record/patch and
   recording at those documented paths, review their provenance, then set the
   two sample manifests' `repairRecorded` flags. Test the fresh recorded sample
   and check the deployed fourth card, timeline and diff. A rehearsal/fixture
   cannot be relabelled a live fixer recording.
4. **Sean, separate workflow review:** extend the read-only same-head fixture
   artifact path with a trusted draft-PR publisher only after inspecting the
   pinned patch and authorization boundary. Never run fork game code with a
   writer token or model secret; never auto-merge. The publisher is still code
   to build and review, not a dispatch this audit can give as already available.

## #422 — vision on an outside project

[Issue #422](https://github.com/Expectrail/Expectrail/issues/422) asks for the safe
two-job workflow, tests and the **first** Sean-started kinematic-character run,
with its actual verdicts on #263, whatever they are. **Closes #422.** It does not
ask that the first vision run accept the game.

| Case | Evidence on main, or missing |
| --- | --- |
| Manual project/cap input, cap > 0 and at most $2 | Existing `.github/workflows/outside-vision.yml`; `tests.test_outside_vision.CaptureJudgeTest.test_cli_checks_cap_before_observer_and_writes_spend_even_on_failure`. Workflow read only in this audit. |
| Capture has no secret, read-only token, pinned variants, sandboxed replays | `tests.test_outside_vision.WorkflowTest.test_judge_never_fetches_or_starts_an_outside_project`; `CaptureJudgeTest.test_capture_pins_each_variant_and_requires_the_sandbox`. |
| Trusted main-only judge downloads only data, never runs the outside game | Same workflow test checks every judge step for game/harness/fetch references; `CaptureJudgeTest.test_saved_gate_runs_no_process_and_records_the_real_trees_and_both_observers` makes any subprocess raise. |
| Saved replay identity/digests checked before a model call | `CaptureJudgeTest.test_corrupt_last_variant_is_refused_before_any_model_call`, `test_a_symlink_a_missing_frame_and_an_extra_file_are_refused`, `test_swapping_variant_folders_is_refused`. |
| Gate uses both observers; findings/spend/table uploaded | `CaptureJudgeTest.test_saved_gate_runs_no_process_and_records_the_real_trees_and_both_observers`, workflow's summary/upload steps. [First real run](https://github.com/Expectrail/Expectrail/actions/runs/43559500793) capture and judge jobs both succeeded; job status and actual $0.7600 / 304-request spend log were read in this audit. |
| First run started by Sean and actual verdicts recorded on #263 | [The recorded first-run comment](https://github.com/Expectrail/Expectrail/issues/263#issuecomment-6874615831): pinned **needs-review**, broken **reject**, harmless **needs-review**, player found in 0/120 frames, $0.76. This meets the literal Done when and honestly exposes the vision failure. |
| Docs explain how to read a vision result and what verified means | [outside-projects.md](outside-projects.md#first-outside-game-verified-with-vision-november-14-2026), including the later [43652198623](https://github.com/Expectrail/Expectrail/actions/runs/43652198623) accept/reject/accept/reject result, calibration, cap and renderer-drift limits. |

No Sean step is left for **this issue**. Dodge readiness in #555 is a separate
preparation, explicitly not live vision evidence. Its optional future dispatch
is already [spelled out](dodge-vision-ready.md#seans-single-live-step-not-performed-here);
do not spend again to satisfy an already completed first-run requirement.

## #329 — a first route from the input map

[Issue #329](https://github.com/Expectrail/Expectrail/issues/329).
**Closes #329** at this pin, for the original two projects/input-map scope.
The existing `capture-smoke` job in `ci.yml` explicitly runs
`tests.test_auto_route_engine -v` with `EXPECTRAIL_ENGINE_TESTS=required`.
This audit also reran those unmodified tests on real pinned Godot: four pass,
zero skips; [recorded output](p0-closeout-audit/route-engine.txt).
The literal `python3 -m expectrail.cli route --project PATH --auto --out ROUTE`
also returned 0 for [bundled](p0-closeout-audit/route-cli-bundled.txt) and
[crate-run](p0-closeout-audit/route-cli-crate-run.txt), each reporting three
identical traces and player movement. [CLI results](p0-closeout-audit/route-cli-result.json)
record their tick counts and exits.

| Case | Evidence on main, or missing |
| --- | --- |
| CLI reads custom input actions, seeded fixed movement holds, other presses, pauses | `tests.test_auto_route.AutoRouteTest.test_crate_and_bundled_maps_are_checked_three_times_offline`, `test_fixed_pattern_is_balanced_with_pauses_and_uses_physics_rate`, `test_summary_names_actions_durations_and_pauses`; existing `expectrail.route`. |
| Built-in ui actions only if no custom map; explicitly authored ui actions retained | `AutoRouteTest.test_no_custom_actions_uses_builtins`, `test_explicit_ui_actions_are_preserved_without_adding_fallbacks`. |
| Bundled command path: route saved, three identical complete traces, player moves | `tests.test_auto_route_engine.AutoRouteEngineTest.test_bundled_game`: real Godot 4.7.2, 2,094 ticks, movement and three complete equal traces asserted. |
| crate-run: route saved, three identical complete traces, player moves | `AutoRouteEngineTest.test_crate_run`: real Godot, 243 ticks, movement and equality asserted. |
| Unseeded source refused as not deterministic with differing ticks; no route saved | `AutoRouteEngineTest.test_unseeded_random_source_reports_ticks_without_writing_route`: independently randomized RNG, differing ticks **0–242** in this run, no output route. |
| Plain summary distinguishes useful movement from empty/stationary/unbound | `AutoRouteTest.test_stationary_and_unbound_players_are_not_called_useful`, `test_empty_route_is_explicit_even_if_gravity_moves_player`, `test_summary_names_actions_durations_and_pauses`. |
| Do not keep malformed, incomplete, changed-project or overwritten results | `AutoRouteTest.test_incomplete_or_malformed_trace_does_not_publish`, `test_changed_project_is_not_certified`, `test_existing_output_is_never_overwritten_or_replayed`. |

No approval, live vision or Sean dispatch is required here. Three equal headless
traces do not prove determinism for every seed, image or future run. Menu-first,
pointer, touch and arbitrary UI discovery are separate work; open #559/#570
are not silently credited as merged and do not block these original cases.

## #370 — local app

[Issue #370](https://github.com/Expectrail/Expectrail/issues/370).
**Part of #370**: offline parity and an outside-project browser use exist;
the original first-user installation/broken-and-fixed trial does not.

| Case | Evidence on main, or missing |
| --- | --- |
| Select project folders and see engine/version, routes, checks, limitations | `tests.test_app_projects.ConfiguredAppTest.test_second_project_lists_its_configured_policy_and_app_cli_have_same_inputs_and_accept`; `tests.test_recorded_renderer_drift.ProjectTest.test_app_inspection_names_both_versions_and_starts_no_job_or_model`; [app guide](app.md). Renderer/version is probed by the existing doctor. |
| Missing engine/display/OpenGL explained before live-vision verification | **Gap fixed here:** `tests.test_p0_closeout.AppSetupInspectionTest.test_live_vision_inspection_names_missing_tools_before_verification`; three missing-tool subcases now retain the doctor's reason/fix and set the existing warning. `test_available_live_renderer_names_version_without_a_false_warning` is the positive control. No project or model starts. |
| Choose two folders | `tests.test_app.HTTPTest.test_verify_command_and_app_decide_the_same_change`; configured-project test above. Paths can be typed, so no native folder picker is needed for that alternative. |
| Choose two git commits or working copy versus last commit | **Missing.** The app guide explicitly says Git references are not supported. The screen/API take two folders. Requires a selection/snapshot UI and safe backend integration, not a documentation claim. |
| Verify uses the same worker and decisions as CLI | `HTTPTest.test_verify_command_and_app_decide_the_same_change` asserts accept/reject/needs-review parity and matching input digests; configured-project test asserts selected base-policy parity. Stand-in replays/vision, not general engine/model accuracy. |
| Progress, running, cancelled, failed, could-not-be-carried-out all have a view | `HTTPTest.test_running_then_cancel_stops_real_worker_and_child`, `test_dead_worker_becomes_failed_and_late_cancel_keeps_a_verdict`, `test_bad_input_or_spawn_error_cannot_be_success`, `test_stand_in_and_empty_or_failed_workers`; `expectrail.app_page` renders these through `show`/`problem`. Automated state evidence, not a first-user trial. |
| Accept/reject/needs-review in words, viewer/report and unchecked scope | `HTTPTest.test_verdicts_and_existing_report_from_fake_replays`, `test_viewer_owned_finished_files_and_security`, `test_observer_words_follow_findings_and_missing_observers_are_diagnostic`. [Viewer](viewer.md) and app use the existing gate's result; no second judging path. |
| Past runs listed and result reopenable | `HTTPTest.test_history_orders_all_jobs_and_never_upgrades_their_states`, `test_history_and_viewer_require_token_host_and_read_methods`. Older sessions reopen status only; their raw reports/viewers are deliberately unavailable under session ownership. This is a documented limitation, not full historical evidence browsing. |
| Loopback only, random token, Host/Origin restrictions, no arbitrary file serving | `HTTPTest.test_every_route_needs_token_and_no_cors_is_sent`, `test_host_and_origin_are_checked_before_actions`, `test_only_owned_jobs_and_report_files_are_served`; existing `app.create_server` fixes the bind address. |
| Read only picked projects and their selected safe policy files | `tests.test_app_projects.ProjectRequestTest.test_selected_checks_keep_exact_bytes_without_adding_unlisted_checks`, `test_linked_configured_policy_is_refused_by_inspect_and_submission`, and the HTTP file-serving boundary tests above. Snapshots are outside the selected game folders; this is file-selection/boundary evidence, not proof that unsandboxed arbitrary game code is safe. |
| Local page; configured observer is the only model path, under the existing cap | `HTTPTest.test_initial_page_removes_url_token_and_apis_use_header`; `ProjectRequestTest.test_recorded_provider_uses_base_files_and_never_live_fallback`, `test_normal_worker_uses_configured_recorded_answers_without_a_key`. The page has local assets; model selection/spend remains the ordinary verifier's configuration. These are offline/source checks, not a packet-capture privacy measurement. |
| One outside Godot folder shown in the app | #502 [browser run](new-work/2026-11-15-app-same-decision.md): kinematic-character broken copy **reject**, frame 44, reopened history/viewer. #516 [configured follow-up](new-work/2026-11-15-app-any-project.md): app and CLI **needs-review** on unchanged folders, same input digests, exact missing frame-111 image question. These are builder browser uses, not a non-developer trial. |
| Outside unchanged/fixed accept from this recording | **Missing**, if used as an extra demonstration. #516 records a two-pixel frame-111 drift; no matching answer exists. Do not substitute an approximate image or a live fallback. The original outside-folder demonstration does exist above. |
| Someone new to terminals installs from documented steps and verifies bundled broken and fixed without help; stumbles recorded | **Missing.** [app.md](app.md) explicitly leaves the installer and non-developer trial open. Automated Chromium use and CLI parity are not this case. No new first-user result was invented. |

### Exact next steps for #370

1. **Builder follow-up:** add the safe commit/working-copy selection path required
   by the Build scope, and finish the one-time installation instructions
   or installer before putting them in front of a novice. The current source
   install is [README Install](../README.md#install); the current browser flow is
   [app.md](app.md). Do not claim that those files are a tested novice installer.
2. **Sean:** arrange one person who is not a developer and has not used the
   terminal workflow. Give them the exact tested installer/instructions and an
   isolated sample containing the pinned bundled broken and fixed versions;
   have them install, choose the two folders, verify, open both results and
   explain them without coaching. Record the installation/platform, instruction
   revision, every stumble/help request, both job IDs, input digests, decisions,
   observer source, unchecked scope and what they thought each verdict meant.
   A prepared builder browser demo cannot replace this test. Needs-review is a
   result to record, not permission to manufacture an accept.
3. **Sean, only if a fresh outside accept is desired:** use the exact missing
   request in `tests/fixtures/recorded-pixel-mismatch/question.json` and the
   image hashes in #516's work log. Decide whether to re-record with an explicit
   cap on the intended renderer; use the existing secret-free capture/trusted
   outside-vision judge split. Any new saved answer must come from the real
   run and its provenance. This is optional for the already demonstrated
   outside-folder case and not performed here.

## #420 — approvals bind to spec content

[Issue #420](https://github.com/Expectrail/Expectrail/issues/420).
**Part of #420**: enforcement is implemented/tested, seven live specs still
have legacy approvals. [Read-only inventory](p0-closeout-audit/approval-inventory.json)
was produced with `expectrail.approval.state`; no repository spec was approved.
The unchanged existing writer tests operate only on temporary test fixtures.

| Case | Evidence on main, or missing |
| --- | --- |
| Canonical UTF-8 sorted compact JSON omits approval; writer computes digest | `tests.test_approval_binding.DigestTest.test_the_digest_leaves_out_the_approval_and_covers_everything_else`; `WriterAndSchemaTest.test_approve_writes_the_digest_and_the_file_reads_back_bound`; existing schema/writer/reader from #423. Existing tests write only their temporary test fixtures. No repository approval was added here. |
| Body edits invalidate matching-looking approval and never judge a change | `DigestTest.test_every_edit_of_the_body_makes_the_approval_not_count`; `GateTest.test_the_reader_counts_an_edited_approved_spec_with_the_drafts_and_says_why`. |
| Edited only spec yields needs-review, never accept | `GateTest.test_when_the_only_spec_was_edited_after_approval_nothing_is_accepted`. |
| Whitespace/key order preserve digest; copied approval fails | `DigestTest.test_whitespace_and_key_order_do_not_change_the_digest`; `test_an_approval_copied_from_another_spec_does_not_match`. |
| Legacy approval still works but record and PR comment name it | `GateTest.test_an_approval_from_before_binding_still_judges_and_the_comment_names_it_on_accept`. The exception is explicit; do not describe all legacy edits as gate-refused. |
| Gate, Spark and other approval readers use the same rule | `GateTest` above; `SparkOpenTest.test_only_approvals_that_match_their_spec_are_read`; `WriterAndSchemaTest.test_the_comment_knows_the_same_words_as_the_approval_module`; source audit of public `expectrail/`, `agents/`, `tools/` approval references. |
| Merge guard flags legacy or bound spec-body edits that lack a new bound approval | `MergeGuardTest.test_an_edited_spec_under_an_approval_from_before_binding_needs_sean`, `test_an_edited_spec_under_a_bound_approval_needs_sean`, `test_the_guard_runs_the_rule`. |
| Live specs have content digests after Sean's re-approval | **Missing for seven files**, listed below. `tests/outside/specs/dodge-play-area.json` is already bound. The checkout app's three draft checks have no approval and must remain drafts. Archived mutation evidence was not migrated or rewritten. |

### Exact next step for #420 — Sean only

In a dedicated reviewed re-approval change, run the existing writer once per
live file after reviewing its full current meaning. **These commands were not run:**

```sh
python3 -m expectrail.spec_writer approve agents/specs/player-stays-above-ground.json --by sean
python3 -m expectrail.spec_writer approve specs/coins-visible.json --by sean
python3 -m expectrail.spec_writer approve specs/player-always-visible.json --by sean
python3 -m expectrail.spec_writer approve specs/player-stays-above-ground.json --by sean
python3 -m expectrail.spec_writer approve specs/unity/unity-coins-visible.json --by sean
python3 -m expectrail.spec_writer approve specs/unity/unity-player-always-visible.json --by sean
python3 -m expectrail.spec_writer approve specs/unity/unity-player-stays-above-ground.json --by sean
```

Do not approve the checkout drafts or rewrite archived bench catch-specs. In that
same human-owned change, update the tests whose temporary edited copies currently
inherit a legacy approval: `tests/test_ci_gate.py:make_repo`,
`tests/test_two_observers.py:repo` (used by exercised coverage), and the explicit
live-legacy expectations in `tests/test_approval_binding.py`. Re-approval changes
their fixture assumption; do not weaken content-binding checks to hide that.
Run `python3 -m unittest tests.test_approval_binding tests.test_ci_gate tests.test_exercised_coverage`
and the full suite, inspect the seven `approval.state` results as `bound`, then
merge that reviewed approval change. Agents do not supply those approvals.

## Runs and limits of this audit

- Baseline full suite, no EXPECTRAIL_* variables: **4,509 tests**, 488.829s,
  OK (58 skips), no failing/erroring test names. Full log is in the handover.
- [Red run](p0-closeout-audit/red.txt): four tests, four failing subcases
  (three suppressed tool warnings plus missing CLI selection); no product code
  had been changed. [Green](p0-closeout-audit/green.txt): four pass after the fix.
- [Real Godot run](p0-closeout-audit/route-engine.txt): four unmodified tests,
  54.509s, zero skips, pinned engine 4.7.2. Complete trace equality and movement
  asserted; no pixels/model or universal determinism claim.
- Focused/full final results, numpy/PIL import blocking, export scan and docs
  byte count are recorded in [this change's work log](new-work/2026-11-16-p0-closeout-audit.md)
  and the handover. Newly committed evidence is kept below 256 KiB. Full suite
  logs stay in the handover; no bulk archive migration duplicates #572.
- The audit did not run the old live jobs again, install a workflow, approve a
  spec, test a novice, inspect held-out/fresh/blind material or use a paid model.
  A closed plumbing issue does not prove a repair rate, general vision accuracy
  or safety on arbitrary games.
