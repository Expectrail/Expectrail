# Five hosted gate trials, prepared from main (#254)

Source main: `49226b6cdadda80754ecee1c61ed33116aeb9b6c`.
Read [#254 and all seven comments](https://github.com/Expectrail/Expectrail/issues/254).
This change exports the existing `tools.gate_trials` kit (main commit `2b11f5ed`)
and records its evidence boundary. No hosted run was started. #254 remains open.

## Apply the prepared trials

The handover zip contains five mailbox patch series under `trials/`, each starting
at the source main above. Each series has two commits: the common public
fall-through seed, then its trial head. The seed changes collision mask 30 to 14;
the correct head restores 30, and the wrong head changes only a comment. No spec
or approval changes. Preparing them uses an alternate index; tracked game files
are never checked out or edited. The exported bundle preserves the exact prepared
commit IDs and includes the separate new-head successor.

Use an existing disposable public test repository, following the
[existing setup checklist](../tools/gate_trials/README.md#one-time-setup-sean-only).
A strict fix cannot demonstrate repairing a seeded defect against Expectrail's
clean main. The test repository therefore needs the kit's common seeded commit
as its default branch; the prepared trial heads target it. Every series is rooted
at the same Expectrail main, and none belongs on Expectrail's protected branch.

The archive includes `setup-seeded-base.patch`, each head-only patch, each
`pr-body.txt`/`steps.txt`/`plan.json`, all commit subjects and `all-trials.bundle`.
Use the bundle to preserve IDs, or rerun the existing preparer on the frozen main.
Applying a mailbox series with `git am` can change commit IDs; regenerate plans
and the new-head body's two IDs if using that route.

In an existing local checkout that already has source main, import the bundle:

```bash
git bundle verify /path/to/all-trials.bundle
git fetch /path/to/all-trials.bundle 'refs/heads/expectrail-trials/*:refs/heads/expectrail-trials/*'
```

Those are local operations. Replace `REPLACE-OWNER` and `REPLACE-FORK` in the
printed push instructions with the existing parent repository and its existing
fork. The builder executed none of the printed pushes. Each archived plan names
the same seeded base/default branch. Install the existing dedicated Checks App
and its existing `main-only` environment configuration there before opening PRs;
keep caller/capture files identical on base, merge and head. No model key is needed.
Push the common base only once. If Sean then commits the trusted test snippets to
that default branch, record its new SHA and freeze it until all trials finish.
Run only subsequent head pushes from the other plans; never push the old prepared
base over the instrumented branch. The PRs can share the original seeded ancestor
and merge the trusted-workflow-only advance. Capture and judge bind the actual
current PR base, which must also appear in the saved report. Remove instrumentation
after recording the experiments; do not advance the base midway through a trial.

| Trial / patch series | One-line trial-head commit message | Exact expected hosted observation |
| --- | --- | --- |
| (a) `a-correct-fix.patch` | `Expectrail hosted trial: correct-fix` | Evidence success; clearance success; summary accept. Trusted comment names `player-stays-above-ground` failing 3/3 on base and passing 3/3 on head. |
| (b) `b-wrong-fix.patch` | `Expectrail hosted trial: wrong-fix` | Evidence success; clearance failure; summary reject. Same ground check still fails after the change and the comment has its finding/reason. |
| (c) `c-tamper.patch` | `Expectrail hosted trial: tamper` | With the separately installed trusted mutation step: evidence success, clearance failure, `EVIDENCE_MISMATCH` in head check and bound bot comment. Without the step this is an ordinary correct-fix control and should accept. |
| (d) `d-new-head.patch` | `Expectrail hosted trial: new-head` | Start with the correct head. During the trusted post-binding pause, push the separately prepared successor: `Expectrail hosted trial: second head`. Old clearance fails with `Superseded capture or pull request` (or explicit current-merge identity refusal); the new SHA has its own capture/check identity. |
| (e) `e-fork.patch` | `Expectrail hosted trial: fork` | Push head to the existing fork and open into the parent seeded default branch. Evidence/clearance success and demonstrated repair, exact fork head/base binding, candidate contents:read and no secret/environment access; trusted job executes base code and reads fork checkout only as data. |

The correct/fork accept expectations depend on the trusted recorded-answer bank
matching the pinned engine's frames/questions. Main contains clean, fall-through
bug/repair and combat recordings. A mismatch is a failed/incomplete trial with
needs-review, with no live fallback. These runs would demonstrate this public
seed/recording, not a general repair rate or independent live vision accuracy.

## Person-controlled hosted experiments

The [proposal snippets](proposals/254-hosted-controls.yml.txt) are for Sean to
review/install only in the disposable repository's trusted workflow. They are
literal insertions with a repository and trial-branch guard. They do not alter
the caller/capture workflows or production main.

For tamper, inject immediately after the verified download, before judgment. The
existing mutator changes one trace byte while retaining the manifest. It preserves
the original before replacement. This tests the hosted reader with substituted
local downloaded bytes. GitHub's immutable uploaded artifact remains unchanged;
a normal PR cannot perform an after-upload substitution.

For stale-head proof, pause after `Start the checks and identify the base` has
written state in the completed-event judge. After the first capture finishes and
that pause starts, push only the provided successor to the original head branch.
Save old/new SHAs, both capture times/attempts, old refusal and new head's own
checks. An environment hold before state creation, a skipped start, a timeout,
or an old accept completed before the push does not demonstrate stale refusal.
Keep incomplete attempts and repeat rather than crediting them as passes.

For the fork trial, additionally save GitHub's effective candidate token
permissions and the two job configurations. Confirm the candidate has no App or
model secrets, no environment, no persisted checkout credential, and runs only
sandboxed game code. The publisher secret belongs only to the parent's trusted
job; that job loads its own trusted revision, evaluates pinned base policy and
executes nothing from the fork. The public reader checks the published statement
and bindings; effective secret reachability also requires this hosted job audit.

For each PR, run the existing public reader after it completes:

```bash
python3 -m tools.gate_trials read --repo OWNER/TEST-REPO --pr NUMBER
```

Save PR/capture/completed-judge URLs, both App check URLs, base/head/merge SHAs,
run attempts, the bounded comment and reader output. Keep full bundles off main;
follow [the evidence-storage work in #566](https://github.com/Expectrail/Expectrail/issues/566). Remove temporary trusted delay
and mutation steps through Sean's review path after the two controls are recorded.
Repository settings and non-bypass merge enforcement remain person-run steps in
the [existing checklist](../tools/gate_trials/README.md#branch-enforcement-checklist-sean-only).

## Done when audit against source main

Names below are existing executable tests rerun for this handover. `HeadChecksTest`,
`SplitGateTest`, `WorkflowSafetyTest`, `VerifyTest` and `RenderTest` are in
[tests/test_ci_gate.py](../tests/test_ci_gate.py); `ReaderTest`/`TamperTest` are in
[tests/test_gate_trials.py](../tests/test_gate_trials.py). Stand-in replays/GitHub
transports do not fill a hosted trial row.

| #254 case | Evidence on main | Hosted evidence still required |
| --- | --- | --- |
| Correct fix: both head checks green | `tests.test_ci_gate.SplitGateTest.test_correct_fix_uses_six_sandboxed_replays_and_trusted_judge_accepts`; `HeadChecksTest.test_clearance_accept_only_and_interrupted_runs`; `tests.test_gate_trials.ReaderTest.test_correct_fix_requires_real_repair_demonstration_in_comment` | Prepared (a), real engine and exact 3/3 demonstrated repair in its bound comment. Existing saved #514 accept is generic, not this trial. |
| Wrong fix: evidence complete, clearance failed | `tests.test_gate_intent.TheGate.test_a_fix_whose_check_still_fails_on_the_head_is_rejected`; `HeadChecksTest.test_clearance_accept_only_and_interrupted_runs`; `ReaderTest.test_wrong_fix_requires_failure_and_named_failing_check` | Prepared (b), reject and actual named after-failure. |
| Between-job edit refused as EVIDENCE_MISMATCH | `SplitGateTest.test_bundle_edits_fail_before_the_observer`; `HeadChecksTest.test_download_checks_the_attempt_digest_and_size_and_keeps_token_on_github`; `tests.test_gate_trials.TamperTest.test_mutated_capture_is_refused_by_the_actual_judge_before_any_observer` | Prepared (c) plus Sean's trusted mutation proposal; local mutation alone is incomplete proof. |
| New head makes old clearance stale | `HeadChecksTest.test_new_head_new_attempt_and_changed_intent_each_block_old_accept`; `ReaderTest.test_new_head_requires_old_refusal_and_after_capture_timing` | Prepared (d), post-binding push window and old/new public receipts/check URLs. |
| No secret in any job that runs PR code; fork boundary | `WorkflowSafetyTest.test_the_untrusted_workflow_has_no_secret_and_no_write_permission`; `HeadChecksTest.test_only_dedicated_publisher_can_publish_clearance`; `WorkflowSafetyTest.test_the_trusted_job_reads_the_head_as_data_and_runs_only_trusted_code`; `ReaderTest.test_fork_requires_different_repository_and_trusted_boundary_comment` | Prepared (e), actual fork and effective job-permission/secret boundary inspection. |
| Candidate replay sandboxed | `SplitGateTest` requires sandbox=require on every captured replay; capture workflow explicitly enables namespaces and calls base `ci_bundle.capture`, which passes require | Existing workflow/configuration and offline test; retain actual hosted isolation counts for all trial captures. |
| Trusted data-only judge validates schema, sizes, digests, completeness, tree and writer version | `SplitGateTest.test_bundle_edits_fail_before_the_observer`, `test_complete_capture_is_refused_if_either_checkouts_game_tree_differs`, `test_extra_frame_with_consistent_digests_is_refused_before_observation`, `test_resolution_change_with_consistent_digests_is_refused_before_observation`; `HeadChecksTest.test_schema_example_and_extraction_limits` and `test_caller_and_reusable_workflow_must_match_the_base_and_test_merge`. Judge tests forbid subprocess.Popen | Code/tests implemented. Hosted tamper experiment records the same boundary in GitHub. |
| Interrupt/timeout never clears | `HeadChecksTest.test_clearance_accept_only_and_interrupted_runs`; `SplitGateTest.test_interruption_never_publishes_a_partial_capture` | Tests already exercise cancelled/timed_out/failure; any hosted interruption is retained as incomplete, not counted as one of the five successes. |
| Base checks/routes, bounded comment, held-out counts only | `VerifyTest.test_the_checks_come_from_the_base_so_a_change_cannot_weaken_them`; `RenderTest.test_the_comment_stays_under_githubs_limit`; `RenderTest.test_held_out_lines_are_counts_only`; workflows use public routes only | Existing implementation/tests. No private material or new hosted claim used here. |
| Require only clearance; bypass outside guarantee | [CI deployment guide](ci-gate.md#require-expectrail-clearance-on-the-protected-branch), existing kit branch-rule checklist | Sean configures the disposable repository and records blocked non-bypass merges. Expectrail's own clearance stays advisory under its current policy. |

The historical accept/refusal fixtures and their public URL sidecars are under
`tests/fixtures/gate_trials/`. The reader's fixture mode was rerun offline. They
show existing publisher behavior and do not replace any of the five trials.
All implementation is reused; this patch adds the frozen trial export/audit and
person-only proposal. No contract or decision rule changes. **Part of #254.**
