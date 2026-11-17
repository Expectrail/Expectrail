# Reproduction on the public bench: 17 of 24 (71%)

Generator offered: `baseline` (expectrail/jit/offer.py). This is the generator as it was before steps 3 and 4 of issue #285. A record made with another setting is counted as no result.

From `jit.yml run 43465090517, attempt 1, at 1e6055004dccfd90bc0f4d132823784838718627`. A defect is reproduced when a generated check passed on the clean game 3 times of 3 and failed on the bug build 3 times of 3, with and without the no-fix candidate.

- Reproduced: 17 of 24 (71%); not reproduced: 7; no result: 0
- Of the defects that change the engine's record on a library probe: 16 of 19 (84%)
- Of the defects nothing was tuned on: 13 of 20 (65%)
- Checks kept (passed on the clean game 3 of 3 and failed 3 of 3 on a near miss): 91
- Spend: $2.0492 in all, at most $0.1722 for one defect; over the $2.00 cap: 0
- Misses by reason: no-signal 2, wrong-predicate 1, undetermined 4

| Defect | Family | Tuned on | Library probes see | Proposed | Kept | Outcome | Reason, or why no result | Spend |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `air-jump` | movement-input | yes | signal | 6 | 6 | reproduced | `jit-c1`, `jit-c2`, `jit-c3`, `jit-c4`, `jit-c5`, `jit-c6` | $0.0655 |
| `gun-cooldown` | timing-cooldowns | yes | signal | 6 | 6 | reproduced | `jit-cooldown-count-left-eq`, `jit-cooldown-count-right-eq`, `jit-cooldown-gap-left-eq`, `jit-cooldown-gap-right-eq`, `jit-cooldown-interval-left`, `jit-cooldown-interval-right` | $0.0439 |
| `body-flip` | movement-input | yes | signal | 7 | 7 | reproduced | `jit-face-hold-left`, `jit-face-jump-left`, `jit-face-move-fire-left`, `jit-face-reverse`, `jit-sym-flips-hold`, `jit-sym-flips-shoot`, `jit-sym-mismatch-jump` | $0.0662 |
| `enemy-ledge` | spawning-enemies | yes | signal | 6 | 6 | reproduced | `jit-e1`, `jit-e2`, `jit-e3`, `jit-e4`, `jit-e5`, `jit-e6` | $0.0783 |
| `bullet-through-enemy` | collision-physics | no | signal | 4 | 4 | reproduced | `jit-c1-kill-count`, `jit-c2-extent-move`, `jit-c3-extent-shoot48`, `jit-c4-extent-shoot12` | $0.0589 |
| `platforms-not-solid` | collision-physics | no | signal | 5 | 5 | reproduced | `jit-c1-landing-sooner-base`, `jit-c2-landing-sooner-w40`, `jit-c3-landing-sooner-w80`, `jit-r-jit-c4-repl-38`, `jit-r-jit-c5-repl-42` | $0.1490 |
| `floaty-fall` | collision-physics | no | signal | 5 | 5 | reproduced | `jit-check-w0-double-multi`, `jit-check-w0-single-double`, `jit-check-w40-double-multi`, `jit-check-w40-single-double`, `jit-check-w80-single-double` | $0.0715 |
| `jump-always-full` | movement-input | no | signal | 6 | 6 | reproduced | `jit-double-higher-w40`, `jit-hold-higher-than-tap`, `jit-tap-low-l40`, `jit-tap-low-w0`, `jit-tap-low-w120`, `jit-tap-low-w80` | $0.1013 |
| `slow-left` | movement-input | no | signal | 5 | 5 | reproduced | `jit-c4`, `jit-c5`, `jit-r-jit-d1`, `jit-r-jit-d2`, `jit-r-jit-d3` | $0.1722 |
| `slides-after-stop` | movement-input | no | signal | 6 | 6 | reproduced | `jit-c1`, `jit-c2`, `jit-c3`, `jit-c4`, `jit-c5`, `jit-c6` | $0.0794 |
| `no-shooting-in-air` | movement-input | no | none | 2 | 1 | reproduced | `jit-c4` | $0.0546 |
| `jump-needs-rest` | movement-input | no | signal | 8 | 8 | reproduced | `jit-c1`, `jit-c2`, `jit-c3`, `jit-c4`, `jit-c5`, `jit-c6`, `jit-c7`, `jit-c8` | $0.0703 |
| `double-jump-once` | state-counters | no | signal | 4 | 4 | reproduced | `jit-c1`, `jit-c2`, `jit-c3`, `jit-c4` | $0.0681 |
| `coin-stays` | state-counters | no | signal | 7 | 0 | not-reproduced | wrong-predicate: `a signal moves on a library probe, and none of the 7 proposed checks failed 3 of 3 on the bug build` | $0.1199 |
| `coin-counts-twice` | state-counters | no | none | 6 | 0 | not-reproduced | undetermined: `the record is the same on every library probe: no route reaches the behaviour, or it shows only on screen` | $0.0778 |
| `coin-counter-stuck` | hud-text | no | none | 6 | 0 | not-reproduced | undetermined: `the record is the same on every library probe: no route reaches the behaviour, or it shows only on screen` | $0.0815 |
| `gun-cooldown-long` | timing-cooldowns | no | signal | 6 | 6 | reproduced | `jit-c1`, `jit-c2`, `jit-c3`, `jit-c4`, `jit-c5`, `jit-c6` | $0.0496 |
| `enemy-missing` | spawning-enemies | no | signal | 6 | 6 | reproduced | `jit-c3`, `jit-c4`, `jit-c5`, `jit-c6`, `jit-r-jit-c7`, `jit-r-jit-c8` | $0.1183 |
| `enemy-fast-left` | spawning-enemies | no | signal | 6 | 6 | reproduced | `jit-enemy-extent-long-vs-reverse`, `jit-enemy-extent-long-vs-short-left`, `jit-enemy-extent-long-vs-short-right`, `jit-r-jit-enemy-extent-long-vs-jump-short`, `jit-r-jit-enemy-extent-long-vs-movefire-right`, `jit-r-jit-enemy-extent-long-vs-shoot-right` | $0.1167 |
| `enemy-slides-when-shot` | spawning-enemies | no | signal | 4 | 4 | reproduced | `jit-c1`, `jit-c2`, `jit-c3`, `jit-c4` | $0.0836 |
| `enemy-walks-backwards` | visibility-rendering | no | none | 6 | 0 | not-reproduced | undetermined: `the record is the same on every library probe: no route reaches the behaviour, or it shows only on screen` | $0.0361 |
| `camera-stops-right` | camera-viewport | no | trace-only | 6 | 0 | not-reproduced | no-signal: `the engine's record differs on a library probe and no signal reads the difference` | $0.1485 |
| `camera-cut-top` | camera-viewport | no | trace-only | 6 | 0 | not-reproduced | no-signal: `the engine's record differs on a library probe and no signal reads the difference` | $0.0517 |
| `bullet-behind-scenery` | layering-draw-order | no | none | 8 | 0 | not-reproduced | undetermined: `the record is the same on every library probe: no route reaches the behaviour, or it shows only on screen` | $0.0863 |
