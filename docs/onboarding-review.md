# Review a game without reading JSON (#331)

Install the contracts extra (`pip install 'expectrail[contracts]'`). Pillow is optional:
without it, small PNGs still work, but other images and crops can be unavailable.
An unavailable object cannot receive a yes.

1. Run `expectrail onboard --project PATH`. Expectrail reads the project and its first
   route, uses a locally installed pinned Godot for a clean replay when available,
   and writes `expectrail-review.html`. It never downloads an engine or calls a model.
   An unresolved init draft keeps the existing binding chooser; resolve it first.
2. Open the page. Each object has a sprite, three measured frames, orange engine
   boxes and, when supplied, cyan recorded observer boxes and scores. Read each
   check's sentence, object, condition, window, pass/fail description and broken-copy
   result. “Not exercised” is never a pass. Engine diagnostics are not vision evidence.
3. Choose yes or no for every object and draft check. Enter your own name, then
   click **Save review answers**. There are no default yes answers. The browser only
   downloads an answers file; it cannot write your project or approve a check.
4. A person runs `expectrail onboard --approve expectrail-review-answers.json`.
   Only selected checks receive a content-bound signature through the shared approval
   writer. Declined checks stay unchanged. Confirmed bindings and selected checks go
   into the project config. A missing name, stale check/input, incomplete answer,
   unmeasured object, linked destination or invalid timing refuses the import.
   Agents must never run this step on real specs.

Keep the adjacent `.expectrail-onboard-*` directory with the original page: its
hashed review record binds the downloaded answers to the reviewed files. Re-running
with the same output path refuses to overwrite it; use `--out NEW.html` for a new review.
A page copied alone is still viewable, but cannot apply decisions without that record.
No server, browser storage or external requests are used.

For captures already made, add `--evidence CLEAN_FOLDER`, repeat
`--broken NAME=CAPTURE_FOLDER`, and optionally add `--recording ANSWERS.json`.
Each capture contains `trace.json`, `replay.json` and `frames/f00000000.png`, etc.
Observer answers match the PNG digest and exact prompt. Missing recorded answers stay
missing; there is no live fallback. This command displays existing answers; it does
not yet orchestrate observer calibration and proof. Those stages are recorded as
skipped, with a reason. Review-ready machine time is not a tuned/proven onboarding time.
Human time runs from page opening to the person's import and is recorded separately.

## Examples from the public trials

Open [Breakout](onboarding-examples/breakout.html) or
[Dodge the Creeps](onboarding-examples/dodge.html). Both are read-only examples;
their download action cannot create applicable answers. No person has approved
anything through these examples. Raw captures are not committed.

The generator is `python3 -m tools.onboard_examples --breakout LOCAL_PINNED_GAME
--dodge LOCAL_PINNED_GAME --artifacts NEW_FOLDER --out docs/onboarding-examples
--godot LOCAL_PINNED_ENGINE` (one command; local Xvfb is required). Source pins and
patches are the public trial inputs in `tests/outside/`. `--reuse-captures` only
regenerates summaries from an earlier artifacts folder. Per-page size is bounded at
120 KiB. Repeated PNGs reuse inline SVG images instead of duplicating image bytes.
PR #572's evidence rule is **256 KiB for the sum of complete added/replaced docs files**,
not a per-image allowance.

Breakout uses the exact two unapproved PR #570 drafts and pointer route at
`e14e0c4a27b2fb5798405723b64312b15833d91d`. The read-only generator consumes that
commit's public `docs/outside-trials/breakout-pointer/trial-evidence/` captures,
verifies the route/trace/PNG hashes against the paired replay records, and evaluates
the drafts offline. Clean and harmless pass both raw engine checks. Broken first
violates the paddle check at frame 20; its ball check needs review because the
paddle's required movement is missing. These are draft diagnostics, not gate verdicts.

Fetch that public commit locally before generating the examples:
`git fetch --no-tags origin e14e0c4a27b2fb5798405723b64312b15833d91d`.
The generator never fetches or executes that commit's code. Pending pointer/menu
support belongs to PR #570's dependency stack; this patch does not backport it.
The Breakout page is an offline review of those frozen trial inputs, not a claim
that this branch can replay the pending pointer route or apply its policy today.
Dodge shows the existing approved engine check without changing its approval.
Its review diagnostic compares configured drawing boxes with the existing region:
clean and harmless fail first at frame 134, broken at 97. The existing approved
engine trial checks an origin-derived box; these drawing-box diagnostics are not
equivalent to that approved origin check, nor to vision evidence. The disagreement
is exposed for review; this patch changes no check, region, threshold or gate result.
Dodge was captured locally; Breakout uses the recorded public trial described above.
Both show engine-only diagnostics, with no vision answers or live model calls. They establish page plumbing, not visual verification.

## #331 audit

Baseline: branch head `ada4c34f948096e309632c00faf28a52c16cce50`; the relevant onboarding
files are unchanged on fetched main `ba050a770f6010c430b51c6a93cf1e81d2cccff5`.

| Done when case | Evidence on main before this patch, or missing | This patch / remaining |
| --- | --- | --- |
| Bundled game and crate-run produce the full offline page using recorded observer answers | **Missing.** `tests.test_onboard.ReviewTest.test_download_preserves_every_binding_and_the_game` proves the bundled binding/art chooser; `tests.test_project_config.SchemaTest.test_the_example_and_the_crate_match_and_validate` proves crate config only. No three-frame/check review. | Three frames, boxes, scores, plain check rows and capture/recording inputs added. `tests.test_onboard_review.HumanReviewTest.test_exact_recorded_answers_draw_cyan_box_and_missing_answers_stay_missing` proves exact offline answer replay with a labeled synthetic client. Local real-engine bundled/crate page smoke also uses recorded engine stand-ins, not recorded vision. Full tuned/proven real-observer flow remains missing. |
| Answers file becomes config and approved specs accepted by the gate | **Missing** for onboard. `tests.test_approval_binding.WriterAndSchemaTest.test_approve_writes_the_digest_and_the_file_reads_back_bound` proves the older separate signing writer. | `test_synthetic_human_answers_use_shared_content_binding_and_gate_reader` proves new import, config, same writer, digest and existing gate reader on invented temporary specs. No real approvals were made. This is gate policy loading, not a newly measured accepted game change. |
| No person's name means refusal | **Missing** for onboard (there was no import command). | `test_missing_name_refused_before_any_write`; browser also requires a name. |
| Timing record validates, separates machine/human and names skips | **Missing.** Old chooser writes no timing contract. | `onboard-timing/v1`, measured review-ready and human intervals, named clean replay/tuning/proof skips; covered by synthetic import and invalid-timing tests. No tuned/proven duration claimed. |
| First outside onboarding number from #263 | **Missing.** Existing outside engine/vision trial records are not a person's timed page review. | Still missing: Sean's actual timed review and the outside calibration/proof trial. Engine-only examples are not this number. |

**Part of #331.** The human review/import surface is implemented. Remaining: connect
observer tuning and proof to the onboarding sequence, record the bundled/crate
end-to-end flow with genuine recorded observer evidence, demonstrate a gate-accepted
change from the reviewed policy, and record a person's outside trial timing. No
“hooked in within N minutes” claim is supported by this patch.
