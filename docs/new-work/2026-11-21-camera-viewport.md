# Draft a viewport containment check for traversal (#727)

## What changed

The draft checks the bound player drawing box against the 800 by 480 viewport during the
rightward traversal. The existing world-space checkpoint independently establishes that the
player reached the right-hand walkway. The check intentionally compares captured placement
with the viewport and uses the existing contracts. The evaluation plan distinguishes viewport
framing from a world-position requirement.

## What was run

- Godot 4.7.2 on main `640db93`. Clean and comment-only passed 3/3. The committed right-limit
  defect and the fixed-camera control failed decisively 3/3 each. All runs recorded the full
  window. The fixed-camera control retained 20 of the 63 geometry observations and produced
  an explicit overhang before the player left the view.
- The frozen-player control returned needs-review 3/3. Its geometry was present, and the
  world-space route checkpoint did not fire. The gate reader found one draft and zero approved
  checks.
- The documented command reproduced all 15 outcomes. Two further edge measurements confirmed
  the right-limit box overruns the viewport while clean retains horizontal clearance.
- Fetched the required historic commit and verified 18 documentation links. The full
  `python3 -m unittest discover -s tests -t .` suite passed with 5,871 tests reported and
  83 skipped.

## Not done

The measurements are headless engine geometry diagnostics without Bubblewrap isolation.
High-platform framing, rendered pixels, and human approval remain outside this result.

## Files

- [Project bindings](../../specs/drafts/727/camera-viewport/expectrail.project.json)
- [Draft](../../specs/drafts/727/camera-viewport/checks/player-stays-in-viewport.json)
- [Measurement](../measurements/727-camera-viewport.md)
- [Family coverage](../measurements/721-family-coverage.md)
- [Evaluation plan](../evaluation.md#frame-of-reference-for-positional-predicates)
- This work-log entry.
