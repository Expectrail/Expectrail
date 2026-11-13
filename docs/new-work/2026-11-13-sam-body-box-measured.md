# The body's own box, first live run

## What changed

`docs/sam.md` records the first SAM probe that asked with the player's own collision box from the
engine (`box` body, the `body` field added in #369), against the four predictions the typed 48 by 68
box was held to.

## What was run

SAM probe run 43351238364, dispatched by Sean on main at 27f0809 (the merge of #369): probe mode,
`anchor` ticked, `box` body, `lift` 0, `clean_routes` coins,combat,traversal, cap $0.50. 131 calls,
$0.33 reserved. Its inputs, rule results and per-frame answers were read from the `sam-probe-results`
branch under `43351238364/`.

- No clean-looking frame under 0.8: held, 75 frames, lowest 0.879.
- Missing texture passes the pairs: held, 13 of 13 each; largest confidence fall 0.008.
- Sinking v2 differs in every compared frame: held, 13 of 13.
- Both layering runs fail: held, 8 of 13 each; frame 30 at 0.82 caught by size.
- The range rule set on smoke alone fails clean combat frame 50 (height 66.5 against at most 64.5).
  The pairs do not compare it.

No code changed. The full suite on this branch: 2669 tests OK, 27 skipped.

## Not done

- The answers were not added to `tests/data/sam-anchor/` as recorded answers.
- Pairs on the coins, combat and traversal routes: the unchanged game was run on smoke only.
- The check in the gate (#327).

## Files

- `docs/sam.md`
- `docs/new-work/2026-11-13-sam-body-box-measured.md`
