# Compare a partly off-screen player with its visible part (#263)

## What changed

Started on the supplied `chatgpt/263-clipped-player` branch at current main
`ed6f2960f173c0e38e67336843bcf1b1fab56259`, after reading AGENTS. Applied my under-review
vision-ready handover first. Its three-way application needed two conflict resolutions:
`docs/outside-projects.md` keeps both additions; `tools/outside_vision.py` combines the new
preflight/calibration scope with main's optional stride and recording/reuse behavior. The planner
keeps that stride. This prerequisite is local commit `256734cb45397d82641272867b5b5017b30bc1ee`.
A subsequent integration fix preserves main's exact RecordedClient identity/diagnosis and
RecordingClient reuse for unconditional checks. No existing identity assertion was changed.
No push or GitHub write.

Reproduced the original clipped control on the same real public captures. Interior calibration
passes found/size/stable 9/9. Candidate frames 94–192 each supply `size-mismatch`: the old observer
compares their clipped dimensions with full calibrated drawnSize, 54×68. Frame 94's visible width
40.334 differs from 54 by 13.666, over max(25%×54,4)=13.5. The unchanged three-frame negative rule
has its first witness 94,95,96; the verdict names 94. Found/stable calibration is not the failure.

The anchored observer now places the fixed clean calibrated rectangle at the logged body centre
and compares its image intersection with the returned image intersection, in game pixels. It
retains the old path on wholly interior bodies. The candidate's collision size cannot replace the
calibrated size. If a centre is outside but the body is partly visible, point into its visible
part. Wholly outside/touching bodies supply an explicit unjudged `outside-view` row, not a pass;
no request is sent. Rows remain in the window. The evaluator preserves earlier counterexamples
and refuses to accept by ignoring such a row, including for fractional visibility assertions.

Clipped frames additionally check visible placement against the same 25%/4 px limits. Wrong
position produces `place-mismatch`, subject to the existing confidence and three-frame rules.
The observations schema, synthetic example, writer and reader change together; old records remain
readable. **No RULES threshold, minimum, confidence floor, nudge, approval, spec or workflow change.**
`expectrail/gate/verify.py` was unnecessary: it already carries observations and delegates their
meaning to the evaluator. It is unchanged.

The positive stand-in used to return legacy feet-offset observer boxes, shifted by 20.75 px on
Dodge. Both present controls instead use the actual logged collision body: full versus clipped.
This is stated explicitly rather than treating the old offset as a valid visual reference.
All dry-run outputs remain labelled stand-in/not vision evidence. No model was constructed.

## What was run

- The historical AGENTS fetch was already performed in the shared repository. Fetched only
  current main and the supplied task branch; user authorization supersedes GitHub claim/PR actions.
- Captures are unchanged from the preceding task: 900 PNGs, 300 per variant, required sandbox,
  pinned Godot 4.7.2/OpenGL3. Digest
  `3c8e74618aa6f8c22ffccb45e369c9ef2a5100025cbae411e56e37981bf906af`.
  No new engine capture, model call or spend was needed.
- `reproduce_before.py` restores the pre-fix anchored code in a process-local module and replays
  the clipped stand-in: calibration 9/9, reject/reject/reject, 99 clean failures at 94–192,
  188 requests/recorded answers, identical recorded replay, zero spend.
- `python3 -m tools.outside_vision_dry_run --project dodge-the-creeps --data CAPTURES --digest
  DIGEST --out NEW_FOLDER`, once for the full physical body and once with `--clip-to-frame`:
  **both** calibrate 9/9 and give accept/reject/accept, then the same recorded replay. Each has
  188/188 recorded answers, zero missing, zero model calls/spend. These are plumbing controls,
  never independent visual evidence.
- Exact question keys equal the before run: 18 calibration point questions, 750 logical point
  questions plus 67 box questions, 188 distinct requests/images, $0.4700 list-price equivalent.
  Four attempts per question: 752 submitted images/$1.8800 for these PNGs. Cap remains $2.00;
  the plan is recomputed for future capture bytes. No live stability questions were added.
- Before editing anchored.py, froze on-screen observations/verdicts from the genuine kinematic
  recording and the public frame-111 recorded/tinted/hidden PNGs. Froze complete findings bytes
  too, on an explicitly synthetic constant-position replay of that same image/engine row; clock
  and caller commit fixed for reproducibility. The tests require byte equality. This is not a
  reconstructed original route, a new hosted run or a measurement of new vision answers.
- `python3 -m unittest -v tests.test_clipped_player tests.test_anchored_observer
  tests.test_dodge_vision_ready tests.test_vision_sampling tests.test_outside_vision
  tests.test_recorded_renderer tests.test_contracts`: **102 passed**, 32.701 seconds. Includes
  16 new edge tests covering missing/size/place defects, scaled cameras, exact tolerance/floor
  limits, wholly outside and mixed windows, confidence, short runs, preserved counterexamples,
  closed contracts and byte-identical on-screen findings.
- Red tests before the fix failed on edge geometry/placement. Final red controls restore only
  the old observer or only the old evaluator, without source/test edits: two observer tests fail
  (19 subcases), and two reader tests fail (place evidence and fractional-visible outside frame).
  The red log is included, not passed off as a successful suite.
- A first attempt raised for any off-screen frame and erased earlier falling-player evidence.
  The original falling-player test caught it; explicit unjudged rows fixed that, preserving
  counterexamples. The old tiles test also exposed that its last seven bodies are partially
  clipped, so its expected/observed dimensions now assert the actual visible dimensions.
- Guard: test change intended (#263). `test_tiles_are_retained_as_not_the_player_instead_of_measuring_their_boundary`
  keeps its negative-evidence/reject/score/raw-box assertions and checks clipped dimensions in
  frames 113–119; interior expectations remain unchanged. The prerequisite clipped-control test
  now requires accept/reject/accept and no clean findings rather than preserving the reported bug.
- Discovery with numpy and PIL unavailable: **0 load errors**, 68 release-gate bodies load.
- Full suite: `python3 -m unittest discover -s tests -t .`: **4,298 passed, 50 skipped**,
  392.844 seconds. No EXPECTRAIL_* variable was set in the shell.
- `git diff --check` passes. The complete patch applies to a fresh detached checkout of the
  supplied base; the same **102 focused tests pass** there in 27.354 seconds. Protected paths
  and approved policy/recording bank bytes are unchanged; RULES values equal the base. The
  handover also checks sequential prerequisite/fix application and file hashes.

## Not done

No live model calls, spend, workflow dispatch, push, PR, comment, setting, key or approval change.
No fresh-*, held-out or blind-set content was read. RULES and the approved checks are unchanged.
The first real SAM calibration/vision result and exact hosted renderer/PNG identity are still
unmeasured here. Sean alone can use the previously documented outside-vision workflow on main,
project `dodge-the-creeps`, cap `2.00`, after review/merge. #263 remains open for genuine vision
measurement and its remaining outside-game work. The patch does not claim object identity beyond
the existing point/size approach, nor information about pixels outside the image.

## Files

- `expectrail/anchored.py`, `expectrail/evaluator.py`.
- `contracts/observations.schema.json`, `contracts/examples/observations-clipped-player.json`.
- `tools/outside_vision.py`, `tools/outside_vision_plan.py`, `tools/outside_vision_dry_run.py`.
- `tests/test_clipped_player.py`, `tests/fixtures/clipped-player/`, and the two intentionally
  updated tests above.
- `docs/dodge-clipped-player.md`, `docs/measurements/dodge-clipped-player.json`, pointers in
  `docs/dodge-vision-ready.md` and `docs/outside-projects.md`, this work log.
- The prerequisite's original work log is retained unchanged as its historical record.
