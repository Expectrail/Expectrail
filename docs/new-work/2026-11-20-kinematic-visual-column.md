# The kinematic-character table says which observer rejected (#263)

## What changed

`docs/outside-projects.md` said the visual observer `agrees` on the broken-collision row of the
kinematic-character table. The recorded findings say its after-change verdict on the ground check is
`not-asked`: the **engine alone** rejected that change. The agreement was a separate paired anchor
comparison on two frames, which is a different statement about a different pair of images.

The old wording read as two observers confirming one real defect. The table now says `not asked on the
ground check`, with a paragraph under it that states which observer rejected and what the paired anchor
comparison did and did not establish.

The last row's explanation is also marked as the one that run recorded. Re-judged on main, the evaluator
reports the player absent at its expected place in 83 of 120 observed frames from frame 0, rather than
the older geometric reading. Same reject, different reason.

## What was run

- Nothing new was measured. This corrects the description of an existing recorded run.
- Source: the offline reproduction of run 43652198623 on main
  ([#244 comment](https://github.com/Expectrail/Expectrail/issues/244#issuecomment-7009221442)), which
  re-judged all four captures from the public artifact with 841 of 860 questions answered from the
  recording and no model call.
- The full suite in 3 parts, and the export scan, on this branch with main merged in.

## Not done

- The other three rows' visual column is left as the run recorded it. Only the broken-collision row's
  wording was contradicted by the record.

## Files

- `docs/outside-projects.md`
- `docs/new-work/2026-11-20-kinematic-visual-column.md`
