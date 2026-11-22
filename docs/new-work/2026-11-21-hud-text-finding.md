# Record the rendered HUD text boundary (#727)

## What changed

Recorded the reachable pause-menu coin counter and the missing rendered-text assertion. The
family inventory links the finding and records the four rendered-text validation arms as unrun.

## What was run

- Reproduced the capability checks with the public 464-tick menu route. The gate schema
  rejected `text-equals`. Both configured pixel observers refused the text role, the
  pixel-only menu omitted the route, and the control generator refused the HUD and Label classes.
- Confirmed that the committed screen diagnostic records 77 of 232 changed frames, starting at
  frame 155, and a HUD change box at frame 166. Its observer field is null. A separate local
  engine-state preflight completed 15 replays for #744. Those anonymous readings establish no
  rendered-text check or gate verdict.
- Ran `python3 -m unittest tests.test_new_work tests.test_linked_paths tests.test_evidence_storage
  tests.test_change_evidence` on main `6291811` with this finding. All 50 tests passed.

## Not done

All four rendered-text replay arms are unrun. #744 tracks the separate exact-score assertion
against a bound engine Label.

## Files

- [HUD capability finding and command](../measurements/727-hud-text.md)
- [Family inventory](../measurements/721-family-coverage.md)
- This work-log entry.
