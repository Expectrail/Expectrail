# Correct-fix pressure on counting pixel checks: a real-engine rehearsal (#271, #286)

**A rehearsal, not the campaign.** The checks are the hand-written `faces-motion` stand-ins for
`enemy-walks-backwards` (`bench/jit/stand-in/enemy-walks-backwards-faces-motion/`), made counting the way
`tests/test_jit_pixel_counting.py` `passing` does (provenance filled in, candidate runs set to pass) and signed
with a throwaway key made in the run. No model wrote them and no trusted job produced them, so this is not
a count for #271's "Done when". It shows that the replay path judges real frames, not that the rules hold
on the bench.

## The run

November 19, 2026, branch `agent2/271-pixel-pressure` (on #638's head 39a7824), Godot 4.7.2-stable
(`harness/get_godot.sh`), a cloud container with 2 CPUs, no model key in the environment.

1. `python3 -m expectrail.jit.cli sensor-bank --out BANK --work DIR`: 7 minutes 18 seconds, 556 templates
   (148 enemy, `met`). Its digest, `b033bf03e7c5...cc60`, is byte for byte the bank the stand-in's checks
   were judged with on November 17, so the frozen checks' setting was used unchanged.
2. `pressure.execute('correct', ...)` with `TemplateSensorObserver(BANK, every=10)`, from a scratch script,
   on the one public defect. The replays ran with sandbox `auto`: Bubblewrap is not installed here, and the
   dispatch itself asks for `require`.

| Candidate | Replays (with frames) | Time | `hold-right` | `reverse` | `move-fire-right` | Status |
| --- | --- | --- | --- | --- | --- | --- |
| The public exact undo (a correct fix) | 9 | 4 min 41 s | pass 3/3 | pass 3/3 | pass 3/3 | `complete` |
| Control: `bench/jit/public/no-fix.patch` in the undo's place | 9 | 4 min 46 s | fail 3/3 | fail 3/3 | fail 3/3 | `failed` |

The first row's record is [`271-pixel-pressure.json`](271-pixel-pressure.json). The control was made by
substituting the no-fix patch for the undo in the same script, so its record names the case
`public-undo`; it is not committed. It is there to show the same path can fail: the bug is still drawn,
and the sensor sees each enemy facing against its motion. No model was called, SAM was asked about 0
images, and nothing was spent.

## What it does not show

- That a counting pixel check made by a model in the trusted job passes every correct fix: only the live
  campaign over all correct fixes, from main, can show that.
- The dispatch's sandbox: these replays were not sandboxed.
