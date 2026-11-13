# The gate on the known-bugs bench: before and after the repair rule (#284)

Written by `python3 -m expectrail.gate.known_bench run` (Godot 4.7.2-stable, engine's record only, no model). Each case is the bug build as the base and the bug build plus the candidate as the head, on the gate's own routes (`harness/routes/smoke.json`, `harness/routes/combat.json`) and approved specs (`agents/specs/player-stays-above-ground.json`), judged once with no stated intent (today's rule) and once declared as a fix (accepted only when a check fails on the base and passes on the head, three times of three).

| Candidates | No stated intent | Declared a fix |
| --- | --- | --- |
| 4 wrong fixes | 4 accept | 4 needs-review |
| 4 correct fixes | 4 accept | 4 needs-review |

Wrong fixes that went from accept to needs-review: 4 of 4. Correct fixes that went from accept to needs-review: 4 of 4.

No approved check failed on any bug build, so nothing here can demonstrate a repair: a declared fix, correct or wrong, is needs-review. A correct fix is accepted as a fix only once a check that reproduces its bug exists: a person's approved check, or a generated check allowed to count (#285, #271).

| Case | Label | Checks | Failed before | No stated intent | Declared a fix |
| --- | --- | --- | --- | --- | --- |
| `known-air-jump-comment-only` (tuned on) | wrong | 2 | 0 | accept | needs-review |
| `known-air-jump-undo` (tuned on) | correct | 2 | 0 | accept | needs-review |
| `known-gun-cooldown-comment-only` | wrong | 2 | 0 | accept | needs-review |
| `known-gun-cooldown-undo` | correct | 2 | 0 | accept | needs-review |
| `known-body-flip-comment-only` | wrong | 2 | 0 | accept | needs-review |
| `known-body-flip-undo` | correct | 2 | 0 | accept | needs-review |
| `known-enemy-ledge-comment-only` | wrong | 2 | 0 | accept | needs-review |
| `known-enemy-ledge-undo` | correct | 2 | 0 | accept | needs-review |

The first reason the gate gave each declared fix:

- 8 of 8 (`known-air-jump-comment-only`, `known-air-jump-undo`, `known-gun-cooldown-comment-only`, `known-gun-cooldown-undo`, `known-body-flip-comment-only`, `known-body-flip-undo`, `known-enemy-ledge-comment-only`, `known-enemy-ledge-undo`): repair-not-demonstrated: this change is declared as a fix, and none of the 2 checks that ran failed before the change, so no check reproduced the reported bug and nothing shows it is fixed
