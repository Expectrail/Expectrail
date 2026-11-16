# A partly visible player is compared with its visible part (#263)

**Stand-ins only; not vision evidence. No model calls or spend.** The original edge rejection is
reproduced on the same 900 public-game PNGs. Both the full-body and clipped-body controls now give
pinned **accept**, broken **reject**, harmless **accept**; each recording replays those results.
The [exact measurements](measurements/dodge-clipped-player.json) include request keys, frame IDs,
raw counterexamples and before/after dimensions. Dodge still needs a genuine vision measurement.

## Exact cause

The nine interior calibration frames (10–90 by ten) pass **found, size and stable at 9/9**. Neither
found nor stable calibration fails. Stability is not asked again on every candidate frame.
At judgment the old observer converts the returned box to game pixels and compares each dimension
with the **full clean calibrated drawnSize**, 54 × 68, even when only part can exist in the image.

| Clean frame | Returned visible width × height | Old expectation | New visible expectation |
| --- | --- | --- | --- |
| 93 | 47 × 68 | 54 × 68 | 47 × 68 |
| 94 | 40.334 × 68 | 54 × 68 | 40.334 × 68 |
| 95 | 33.667 × 68 | 54 × 68 | 33.667 × 68 |
| 96 | 27 × 68 | 54 × 68 | 27 × 68 |
| 180 | 27 × 34 | 54 × 68 | 27 × 34 |
| 192 | 54 × 34 | 54 × 68 | 54 × 34 |

At 94, the width difference 13.666 exceeds max(25% × 54, 4) = 13.5. The answer still holds the
question point (466, 450), but the size comparison records `notDrawn: size-mismatch` first.
This happens on **every frame 94–192, 99 consecutive frames**, on pinned and harmless. The unchanged
missing-player rule needs **three consecutive observations**; 94, 95, 96 form its first witness,
and the completed verdict names the first frame, 94. The engine bounds check still passes clean.
This is a deterministic geometry error in an engine-box stand-in, not a SAM false-alarm rate.

## What changes, without weaker thresholds

An interior frame keeps the original question, comparison, observations and findings bytes. For an
edge frame, the expected clean calibrated rectangle is placed at the engine collision body's
centre, projected with that frame's camera and intersected with the image. Its visible dimensions
are compared with the answer's visible dimensions in game pixels. The candidate's body supplies
place and visibility; changing its size does **not** replace the clean calibrated sprite size.
A full engine rectangle returned by a stand-in is intersected with the image too. Raw negative
answers remain in the evidence; `expectedVisibleBox` makes the comparison explicit.

The found/size/stable thresholds, 25% tolerance, 4 px size floor, 3 px stability floor, nudge,
confidence requirement and three-frame missing-player rule are unchanged. The expected object is
smaller only because the image cannot contain the portion beyond its edge. A missing visible
portion still supplies `no-match`; an incorrect visible size still supplies `size-mismatch`.
At edges the visible box must also be at the expected place: displaced edges beyond the same
25%/4 px limits, or a box not holding the question point, supply `place-mismatch`. Thus a same-size
box shifted down 20 px cannot pass merely by continuing to hold the point. One or two negative
frames stay needs-review; three confident consecutive negatives fail, exactly as before.

If the body's centre is outside but part is visible, the question moves into that visible part.
A wholly outside or merely touching body supplies **`notExercised: outside-view`**, sends no
question and adds no judged frame. It cannot manufacture a pass, including for a fractional
visibility assertion. It also cannot erase an earlier counterexample. All observed rows stay in
the document; no edge frames are silently dropped to meet coverage. Dodge still judges all 183
in-play clean frames against the unchanged approved minimum of 120.

This adds two explicit observations-contract cases, with a schema, synthetic example, writer and
reader in this change. Old observations and recordings remain readable. The evaluator handles
those cases; **`expectrail/gate/verify.py` is unchanged**. No RULES or approval changes.

## Proof and its limits

| Engine-box control; all are stand-ins, not vision evidence | Calibration | Pinned | Broken | Harmless | Recorded answers / missing |
| --- | --- | --- | --- | --- | --- |
| Before, physical body clipped to image | 9/9 on all three rules | reject | reject | reject | 188 / 0 |
| After, full logged physical body | 9/9 on all three rules | accept | reject | accept | 188 / 0 |
| After, physical body clipped to image | 9/9 on all three rules | accept | reject | accept | 188 / 0 |

The former positive control used the legacy engine observer's feet-offset convention rather than
the actual collision body: on Dodge that shifts the box by 20.75 px. Both current controls use the
actual logged physical body, one full and one clipped. That old offset is not a valid reference
for the visible body and is not granted an exception to the new placement check.

Tests cover every edge, corners, a centre outside with a visible part, scaled/translated cameras,
a hidden player, wrong width/height, wrong place with/without still holding the point, exact size
limits and floors, confidence, short negative stretches, a wholly outside frame, mixed windows,
and preserving an earlier failure. A changed collision size cannot redefine the calibrated size.
Guard-disabled red runs restore the old observer or old reader and show the targeted tests fail.

The kinematic fixture uses genuine answers from `tests/outside/recordings/kinematic-character/`
for the repo's public recorded/tinted/hidden frame-111 images. Before changing the observer, its
observations and verdicts were frozen. They remain byte-identical. Complete gate findings also
remain byte-identical on a **synthetic constant-position replay** made by repeating that recorded
image and engine row. This isolates the on-screen observer behavior; it is not a new hosted run,
a recapture, or a claim to reconstruct the original full frame bank.

The same capture digest is retained:
`3c8e74618aa6f8c22ffccb45e369c9ef2a5100025cbae411e56e37981bf906af`.
Dodge's **question keys and counts do not change**: 18 calibration point questions; 750 logical
point and 67 box questions in the full plan; **188 distinct requests/images**, $0.4700 at the repo's
$0.0025/image. Four attempts per question would be 752 image submissions/$1.8800 for these bytes.
The recommended existing workflow cap remains **$2.00**. No extra live stability question is added.
A future renderer can change exact reuse; the plan is recalculated from the incoming capture.

Run the stand-in CLI from the [readiness report](dodge-vision-ready.md), with and without
`--clip-to-frame`, using different new output directories. No key or cap is needed for those dry
runs. Their directories, model/provider, summaries, recording and human reports remain explicitly
labelled stand-in/not vision evidence; they must not enter the production recording bank.

The original report's single live step for Sean stays the same after review/merge: Outside vision,
branch main, project `dodge-the-creeps`, cap `2.00`. No live dispatch was performed. Actual SAM
identification, its calibration result and exact hosted renderer/PNG reproducibility remain
unmeasured here. #263 remains open pending that evidence and its remaining outside-game work.
