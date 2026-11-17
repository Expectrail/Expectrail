# Recorded-renderer closeout audit (#515)

Audited main `d877ddb647161e4af28aa554e7886d91e1b83f5b` on November 16, 2026.
This is **Part of #515**. No new recorded answer, tolerance, live call or game
replay on a second renderer was made. The supplied patch adds local readiness
outcomes and an offline app result/report regression test.

## Each Done when case

| Case from [#515](https://github.com/Expectrail/Expectrail/issues/515) | Evidence on main | Result and remaining work |
| --- | --- | --- |
| A recording names its capture environment; a different replay explains it | [Optional contract field](../contracts/vision-recording.v1.schema.json#L128), [example](../contracts/examples/vision-recording.json#L36), and `tests.test_recorded_renderer.RenderingTest.test_writer_round_trip_names_captures_not_the_judges_environment`, `test_old_recordings_stay_readable_and_do_not_guess_an_environment`, `test_missing_image_names_both_renderer_versions` in [the tests](../tests/test_recorded_renderer.py#L63). [Writer/reader](../expectrail/recorded.py#L111) take provenance from the capture, not the judge's machine. | Implemented for known capture provenance. The kinematic recording identifies LLVM 20.1.2. Four legacy Run it files still have no provenance; their environment cannot honestly be named. Recover capture metadata or re-record before strict rollout. |
| A measured decision about reuse for differing images; hidden, moved, resized and recoloured player never reuse the clean answer | [Measurements and decision](recorded-renderer.md#measurements-before-choosing-a-tolerance), [machine-readable measurements](measurements/recorded-renderer.json), [public fixture provenance](../tests/fixtures/recorded-renderer/README.md), `tests.test_recorded_renderer.RenderingTest.test_measured_visual_changes_never_reuse_the_clean_frame_answer` and `test_published_measurements_reproduce_and_overlap_is_explicit` ([tests](../tests/test_recorded_renderer.py#L212)). | Met by retaining exact PNG SHA-256, question kind and prompt. Differing image bytes have no allowed bound. Rerunning `python3 -m tools.recorded_renderer --out /tmp/recorded-renderer.json` here exactly reproduced the committed measurements. No approximate lookup is introduced. |
| Unchanged kinematic-character is decided on both renderer builds, **or a written reason why that is unsafe** | [Existing written decision](recorded-renderer.md#decision-retain-exact-matching), [original public vision run](https://github.com/Expectrail/Expectrail/actions/runs/43652198623), [outside results](outside-projects.md#first-outside-game-verified-with-vision-november-14-2026), `tests.test_recorded_renderer.RenderingTest.test_anchored_wrapper_preserves_reason_and_original_answer`, `test_anchor_comparison_keeps_reason_when_both_sides_have_no_answer`. | The unsafe-reuse alternative is documented below; there is no claim of accept on both builds. The original capture can use its recorded answers. The other capture's frame 111 lacks an exact answer and needs review. A new app HTTP/worker/report test preserves that result and names both versions, using actual fixture pixels and a stand-in replay. |

The new app test is
`tests.test_renderer_closeout.AppRecordedRendererTest.test_real_missing_pixel_answer_reaches_app_result_and_report_with_both_versions`.
It runs the normal app worker and reads its served report. It repeats one public
trace row/image and substitutes the actual different frame at 111. It is **not** a
full real-engine replay or independent validation of the older full-capture
120/120 and 111/112 results reported in #525's handover. Both live-client entry
points are forbidden during this test.

## Why differing images cannot safely reuse these answers

The two saved 180-frame captures have 179 identical PNG hashes. Frame 111 differs
at two pixels, with a largest channel difference of one. Its changed pixels are
261.017 to 266 pixels from the recorded player box. Both captures identify Godot
4.7.2 and OpenGL3; they identify different llvmpipe builds (LLVM 20.1.2 and 19.1.7).
That is evidence of coincident image/environment differences, not an isolated
experiment proving the driver caused them.

The [same measurement table](recorded-renderer.md#measurements-before-choosing-a-tolerance)
also includes hidden, moved by 3 pixels, resized, tinted and two subtle recolour
probes. A recolour of two player pixels also changes two pixels by one channel
level. A global pixel-count/channel bound admitting this renderer difference
would admit that player change. Distances separate these saved examples, but no
general spatial policy is established: a player box is not a mask of all the
evidence used by every question, and this one frame cannot establish what future
renderer changes at a player edge do. Exact matching therefore remains required.
Hidden and tinted images are actual captures; moved, resized and subtle recolours
are controlled transformations over the actual background, not additional runs.

## What the closed PRs established

| PR | Relevant contribution and limit |
| --- | --- |
| [#516](https://github.com/Expectrail/Expectrail/pull/516) | App verification through project config; identifies the missing frame-111 question. Does not demonstrate full unchanged-game accept on the second renderer. |
| [#525](https://github.com/Expectrail/Expectrail/pull/525) | Optional recording provenance, writer/reader diagnostics, reproducible pixel fixtures and the exact-match decision. Its architect requested normal app result/report coverage; this patch adds that offline integration test. |
| [#528](https://github.com/Expectrail/Expectrail/pull/528) | Doctor/app preflight comparison, capture guard, re-record guide. Four legacy recordings have unknown provenance, so strict capture rollout is still blocked. |
| [#532](https://github.com/Expectrail/Expectrail/pull/532) | Release receipt tests; its local renderer failure report is evidence about the environment, not a renderer fix. |

All four PR bodies/comments and all five issue comments were read. The November
15 issue comment cites green CI run 43768135030 as showing a compatible machine.
The [test job](https://github.com/Expectrail/Expectrail/actions/runs/43768135030/job/132977752331)
did conclude success, but its renderer test log at `2026-11-15T22:18:22.8637309Z`
says `skipped 'Godot 4.7.2-stable is not installed at its configured/cache path or on PATH; see expectrail doctor'`.
That success is not renderer-compatibility evidence. The exact line and job
metadata are in the handover logs.

## Local outcome versus required capture check

`tests.test_recorded_renderer_drift.CaptureRendererTest.test_checked_in_recordings_match_the_capture_renderer`
now reports local incompatibility as a **named skip**, never a successful match:

- `recorded-renderer-mismatch`: known recording and machine environments differ.
- `recorded-renderer-unknown`: a valid legacy recording lacks complete provenance.
- The reason lists all affected files, available recording/machine versions, and
  the fix. If both unknown and mismatched recordings exist, the aggregate is
  unknown and the reason still includes every mismatch.

Malformed recordings and empty collections still fail locally. With
`EXPECTRAIL_ENGINE_TESTS=required`, all incompatibility/unknown/unavailable cases
still fail. Only complete, matching provenance passes this readiness check;
matching metadata alone does not guarantee every image/question is recorded.
The five `LocalCaptureOutcomeTest` tests in
[tests/test_renderer_closeout.py](../tests/test_renderer_closeout.py) exercise
both modes, including corrupt evidence mixed with mismatched evidence.

On this machine, a real Godot 4.7.2 plus virtual-display probe reproduced the old
failure: local LLVM 19.1.7, kinematic LLVM 20.1.2 and four unknown Run it files.
After this patch the same probe is one named local skip; required mode is one
failure. These are readiness probes of an empty scene, not game runs or model
calls. Default full-suite discovery does not find the required Godot 4.7.2 build
(PATH reports 4.6.3) and reports its existing named prerequisite skip. The handover retains all three real-probe logs.

## Sean's remaining steps

1. Recover authentic capture `replay.json` metadata for `clean`,
   `fall-through-bug`, `fall-through-repair` and `gate-combat`, or choose to
   re-record them using the [existing protected recording workflows](recorded-renderer-upgrades.md#re-record-only-sean-dispatches).
   Do not infer the renderer from the runner's OS name or copy another
   recording's provenance. No dispatch was made here.
2. After those files have known provenance, add the strict command from
   [the upgrade guide](recorded-renderer-upgrades.md#check-after-a-runner-image-upgrade)
   to the existing capture job after its smoke capture. This patch changes no
   workflow. An incompatible runner must fail that required check.
3. For a machine whose frame bytes differ, choose a recording made on that
   renderer or explicitly configure live vision and its budget. This patch does
   neither. If closing #515 via its unsafe-reuse alternative, link this measured
   decision in the issue; no GitHub write was made here.
