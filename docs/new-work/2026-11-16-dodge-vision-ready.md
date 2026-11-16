# Prepare Dodge's first vision measurement without a model (#263)

## What changed

Read the outside-project report, anchored RULES, outside-vision workflow/code and the public
kinematic recording. Work is on `chatgpt/263-dodge-vision-ready`, from main
`9773ae5cf6eb77dada559d4929e8ae73fb8e9e84`. No prerequisite patch was needed.

Validate all captured variants and the selected approved check before calibration, including
hashes, complete route clock, input mapping, sandbox receipts, pinned Godot/OpenGL3 and matching
recorded rendering profiles. Conditional checks calibrate only on the original sampled frames
that are visibly in play and have unclipped collision bodies. Hidden frames are not questions.
Successful identical PNG/kind/prompt answers are reused within one job; errors are not cached.
The plan is computed from incoming data before any question and included in the already-uploaded
calibration report. The existing custom-observer path retains the gate's needs-review behavior
for inadequate lifecycle coverage; existing test assertions were not changed.

Added a deliberately labelled engine-box stand-in and recording/replay driver, exact no-model
planner, real-trace/synthetic-PNG regression fixtures, report and machine-readable measurement.
No public contract format changed. No RULES, approved spec, protected file, workflow or game edit.

## What was run

- The required historical AGENTS fetch had already been performed in this shared repository.
  Fetched current main and the supplied branch read-only; no push or GitHub write.
- Fetched only the public pinned demo commit `b761b4cd5718a7118f2c95eb55f181d0a5f004f1`
  and made all three real captures: Godot 4.7.2, software OpenGL3, real required Bubblewrap
  isolation, 300 frames per arm (900 total). Capture digest:
  `3c8e74618aa6f8c22ffccb45e369c9ef2a5100025cbae411e56e37981bf906af`.
  The installed default Godot was 4.6.3, so the cached pinned 4.7.2 binary was selected explicitly.
  Local Xvfb was extracted from a public Debian package; no system installation. A scratch-only
  adapter bound that executable and its display launcher read-only into the normal sandbox.
  The outer sandbox's uid-map restriction initially prevented Bubblewrap; the approved escalated
  capture retained the inner required sandbox, network isolation and confinement. No fake receipt.
- Real geometry: 183 visible clean frames (10–192), 242 broken (10–251). Source capsule is full
  54×68; centre and +3 px nudge are interior and the four sprite textures are opaque there.
  This is geometry, not visual identification. Local llvmpipe LLVM 19.1.7 differs from the recorded
  kinematic CI LLVM 20.1.2; exact hosted renderer/PNG equality was not shown.
- `python3 -m tools.outside_vision_dry_run --project dodge-the-creeps --data CAPTURES
  --digest DIGEST --out NEW_FOLDER`: on real captures, calibration 9/9 on unchanged RULES;
  engine-box stand-in accept/reject/accept, then identical recorded replay, 188/188 recorded
  answers, zero missing. **No model, no spend; not vision evidence.**
- Same command with `--clip-to-frame`: calibration 9/9, then reject/reject/reject and identical
  recorded replay. Clean pinned has 99/183 visual stand-in failures starting at frame 94.
  Only 84 clean in-play frames are fully interior, below the unchanged approved minimum of 120.
  This is a clipped-box stress finding, not a SAM false-alarm measurement.
- Original main's outside-vision implementation, same real captures and positive stand-in:
  887 calls, image-equivalent $2.2175. New exact plan and actual stand-in agree on 750 logical
  point questions plus 67 box questions, 188 distinct successful requests/images, $0.4700 at
  $0.0025/image; at most four attempts per question would reserve $1.8800. Recommend the existing
  workflow maximum cap $2.00 (800 paid attempts). A fresh live capture's byte reuse can differ.
- Initial planner/dry-run disagreement was 191 planned versus 188 actual: it counted point
  questions on the broken arm even though the engine failure skips that observer. Corrected
  the planner to use the same engine short circuit; exact request-key sets now match.
- `python3 -m unittest -v tests.test_dodge_vision_ready tests.test_outside_vision
  tests.test_project_audit.SelectedVisionPolicyTest`: **27 tests passed**, including 13 new tests.
  One initial new assertion used the wrong reason substring and was corrected to the actual
  unchanged reason plus first-frame/count checks. No existing assertion was weakened.
- Red controls with guards disabled only by process-local mocks: bypassing preflight makes
  the corrupt-later-frame test fail (expected ValueError absent); disabling exact reuse makes
  its regression fail (2 calls instead of 1). Both red runs are included in the handover.
- Import discovery with numpy and PIL unavailable: **0 load errors**, 68 release-gate bodies load.
- `python3 -m unittest discover -s tests -t .`: **4,174 tests passed, 49 skipped**, 387.317 seconds.
  No EXPECTRAIL_* variable was set in the shell. The retry/cap test patches and restores its
  cap locally and mocks HTTP; it proves four charged attempts and refusal before a fifth.
- Clean-base patch application: `git apply --check` and apply succeeded; the same 27 focused
  tests passed in 12.908 seconds. Running the dry-run CLI from that independent checkout against
  the packaged captures again yielded 188 answers, accept/reject/accept, identical recorded
  replay and zero model calls/spend.
- `git diff --check`: passed. Full validation logs and the public capture/stand-in artifacts
  accompany the handover.

## Not done

**No live model calls, spend, dispatch, push, PR, GitHub comment, approval, secret or setting change.**
No held-out, blind-set or fresh-* content was read. Dodge still has no live vision evidence and
#263 cannot close from this work. The clipped-edge size risk needs Sean/observer-owner review;
changing protected observer code during PR #493, RULES or the approved policy is outside this task.
After merge and that review, Sean's one live step is documented in `docs/dodge-vision-ready.md`:
Outside vision on main, project `dodge-the-creeps`, `sam_usd_cap=2.00`. It needs the existing
main-only key. Calibration on nine eligible samples needs 9/9 found, size and stable under the
unchanged 90% rules, and passing calibration alone is not a gate accept. Exact hosted renderer
identity and future CI replays remain unshown; no renderer override or fuzzy lookup was added.

## Files

- `tools/outside_vision.py`, `tools/outside_vision_plan.py`, `tools/outside_vision_dry_run.py`.
- `tests/test_dodge_vision_ready.py`, `tests/fixtures/dodge-vision/` (trace vectors and hash aliases;
  unit-test PNGs are synthetic, not screenshots).
- `docs/dodge-vision-ready.md`, `docs/measurements/dodge-vision-readiness.json`,
  `docs/outside-projects.md`, this work log.
