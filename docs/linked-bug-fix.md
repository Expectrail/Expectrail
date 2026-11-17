# A closing link requires a demonstrated repair (#284)

Audited against main `5d25639b7e53e5989cf2eb062544727eeefb02e1`, including
[#284 and its 12 comments](https://github.com/Expectrail/Expectrail/issues/284) and
[PR #500](https://github.com/Expectrail/Expectrail/pull/500). All evidence below is
public; no held-out or blind-set content was read for this work.

A PR body containing `Fixes #284`, `Closes #284` or `Resolves #284` now requires
intent `fix`, in any case. GitHub's other closing-verb forms, qualified references
and GitHub issue URLs also count. Labels and `Expectrail-Intent: none` cannot
cancel the link. `Part of #284` alone does not declare a fix. Without an issue API
lookup, every closing link counts, even to a feature issue, another repository,
or inside a quote or code example. This can require a demonstrated game repair
for a code-only PR. It is deliberately stricter and may need human review.

The PR event already has the body. Both capture and the trusted judge use the same
classifier. Findings and bundles carry `pullRequest.fixLinks`: up to ten matched
phrases with 1-based body line numbers. Only the closing phrase is captured, not
surrounding instructions. The source can tighten intent; it cannot choose a spec,
route, check, model or approval. Reports and comments show the source line. The
trusted judge compares it to the freshly read PR; changed source lines invalidate
stale captures. A legacy accept judged as none is refused when the PR requires fix.
A reject remains reject. Legacy records that already used fix remain readable.

No new token permission or issue API call is required. Optional future label
classification is described only in [a proposal](proposals/284-issue-labels.yml.txt).
Nothing under `.github/` is changed. Upgrading an older pinned action requires
pinning its writer and reader to the same revised commit; an old capture without
the linked-source metadata is refused by a new judge rather than weakened.

## Done when audit

The five shared-rule cases and the CLI path were already on main. The linked-PR
case was missing. Names below are executable tests, not a claim of a CI dispatch.
They were rerun locally with this patch; full-suite results are in the handover.

| Case from #284 | Evidence on starting main | Evidence added in this patch |
| --- | --- | --- |
| Fix with passing base needs review | `tests.test_gate_intent.TheGate.test_a_fix_whose_base_passes_every_check_is_needs_review`; `tests.test_verify_intent.VerifyIntentCLI.test_known_bench_comment_only_fix_is_not_verified_and_default_is_unchanged` | `tests.test_linked_bug_intent.CaptureAndJudge.test_linked_fix_with_passing_base_needs_review_and_downgraded_bundle_is_refused` wires the linked PR through capture and trusted judgment |
| Base fails, head passes: accept | `tests.test_gate_intent.TheGate.test_a_fix_with_a_check_failing_on_the_base_and_passing_on_the_head_is_accepted`; `tests.test_verify_intent.VerifyIntentCLI.test_real_seeded_fix_accepts_only_with_three_demonstrations` (stand-in replay despite the historic name) | `tests.test_linked_bug_intent.CaptureAndJudge.test_event_classifier_drives_existing_capture_and_trusted_judge`: six stand-in replays, shared gate rule, record/page/comment source round trip |
| Head still fails: reject | `tests.test_gate_intent.TheGate.test_a_fix_whose_check_still_fails_on_the_head_is_rejected`; `tests.test_verify_intent.VerifyIntentCLI.test_still_failing_on_the_head_rejects` | Existing rule unchanged; closing link also cannot turn a reject into acceptance |
| Flaky base does not demonstrate repair | `tests.test_gate_intent.TheGate.test_a_flaky_base_failure_does_not_count_as_a_demonstration`; `tests.test_verify_intent.VerifyIntentCLI.test_flaky_base_failure_is_not_a_demonstration` | Existing three-of-three confirmation reused |
| Intent none behaves as before | `tests.test_gate_intent.TheGate.test_the_same_change_with_nothing_declared_is_accepted_as_before`; `tests.test_gate_intent.TheRule.test_none_and_change_are_judged_exactly_as_before` | `tests.test_linked_bug_intent.Links.test_unrelated_references_are_none_and_adding_declarations_never_weakens` |
| Public known bench: wrong accepts become review, counts published | `tests.test_gate_known_bench` and the prior explicit-intent run in `bench/jit/known/gate.md` | New real-Godot [measurement](measurements/284-linked-known-bench.md), [standard record](measurements/284-linked-known-bench.json), `tests.test_linked_bug_intent.BenchDriver.test_existing_bench_and_decision_receive_only_fixed_routes_specs_and_stricter_intent` |
| Linked bug cannot be declared away | Missing: main ignored closing keywords, though explicit labels/body intent already worked | `tests.test_linked_bug_intent.Links`, `EventCLI.test_actual_legacy_gate_command_tightens_none_and_refuses_mismatched_event`, `HeadSnapshot.test_a_body_edit_that_keeps_fix_intent_still_invalidates_the_source_lines`, `TrustedComment` |

## Contracts and both sides

`contracts/findings.schema.json` and `contracts/ci-bundle.v1.schema.json` add the
same closed optional `pullRequest.fixLinks` shape, with linked-fix examples.
`intent.pull_request_metadata` writes it for capture and trusted state; the legacy
gate command also takes it from its existing event. Bundle judgment validates and
compares it, the findings reader refuses linked intent none/change, and the shared
report text renders it. Bad fields/line types, downgrades and stale sources are
tested. Records without links keep their former shape. The request format and its
reader are unchanged: a PR link is CI provenance, not a second request format.

## Real-engine counts and repeat command

The wrapper loads only the intent classifier from the trusted starting commit,
then calls the existing `known_bench.run_case` and `verify.run_gate` with each
classifier's result. Both arms use the same current, unchanged decision rule.
It uses the public bench's four bugs, each with a comment-only wrong fix and an
exact-undo correct fix; it neither generates nor approves checks.

| Candidates | Before: linked body ignored, intent none | After: same body implies fix |
| --- | --- | --- |
| Four wrong fixes | 4 accept, 0 reject, 0 needs-review | 0 accept, 0 reject, 4 needs-review |
| Four correct fixes | 4 accept, 0 reject, 0 needs-review | 0 accept, 0 reject, 4 needs-review |

Recorded with Godot 4.7.2-stable, engine-only, headless and sandbox off, no PNGs or
model calls. No approved check failed on the base in these cases. Correctness
labels alone cannot demonstrate a repair. This shows the intent change's effect,
not vision accuracy, sandbox security, a repair rate or proof a check is about the
reported bug. The CI capture/judge test uses stand-in replay and vision evidence.
There was no CI dispatch and no live model run.

With the pinned engine installed as described in `docs/harness.md`:

```sh
python3 -m tools.linked_bug_bench --work /tmp/linked-known-bench \
  --out /tmp/linked-known-bench.json --markdown /tmp/linked-known-bench.md \
  --provenance /tmp/linked-known-bench-provenance.json
python3 -m expectrail.gate.known_bench show /tmp/linked-known-bench.json
```

The first command refuses before replay if the supplied body does not expose the
none-to-fix transition. The second uses the existing strict bench reader. Raw
command logs and provenance accompany the patch zip; only small records and this
summary are kept on main. Generated checks remain advisory under the existing
rules (#271); this change grants no approval. A check that fails before and passes
after for an unrelated reason can still count, and three replays demonstrate
stability only for that route and machine.
