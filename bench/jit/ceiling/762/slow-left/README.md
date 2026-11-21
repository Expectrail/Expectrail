# Slow-left

With matched left and right input durations from the same starting conditions, the robot must travel in each requested direction, and leftward travel should remain comparable to rightward travel. About half the rightward distance is a counterexample.

The stock two-second hold probes end at different level boundaries. Their clean net displacements were −196.69 px and +401.69 px. The available JIT library probes `jump-l40-x1` and `jump-w40-x1` start at the same spawn and press the requested direction at tick 10 for 40 ticks. Both release movement at tick 50, press jump at tick 60, and end at tick 139. Their clean net displacements were −100.01 px and +100.01 px. The ordinary proposal uses those two probes and `wait-long`, with zero clean displacement.

The two signed floors require more than 75 px in each requested direction. This is approximately 75% of the clean distance, midway between matched travel and the report's about-half counterexample. The signed separation checks the sum of the distances when their directions are correct. The other ordinary forms test whether direct signed equality or screen-range equality can express the comparison. The existing advisory mirror compares negated world-space displacement with its fixed 2 px tolerance. The compound diagnostic requires both signed floors and the mirror to pass.

All forms were frozen before the defect patch was supplied by path to the harness. The candidate-withheld proposal passed the stock parser and proposal loader under `signals-reach-evidence-menu-control`. The source files listed in [frozen.sha256](frozen.sha256) were checked against their recorded hashes before replay. No revision was made.

## Reproduce

Run from a checkout containing this case with the repository's Python dependencies and Godot 4.7.2. The measured product source was `d5b1e8f4016f69fd7285d1ec664ac695da1d465d`. Use a new output directory.

```sh
SLOW_LEFT_WORK=$(mktemp -d /tmp/expectrail-762-slow-left.XXXXXX)
EXPECTRAIL_GODOT=/absolute/path/to/Godot_v4.7.2-stable_linux.x86_64 \
PYTHONPATH=. python3 bench/jit/ceiling/762/slow-left/replay.py \
  --out "$SLOW_LEFT_WORK/reproduction"
```

The runner records three rounds per build on fresh harness copies. It writes the per-run signal values, trace hashes, route hashes, coverage and verdicts to `raw-results.json` under the output directory. The frozen-player patch comes from the stock control generator. The comment-only arm appends a GDScript comment to a copy of the clean player script.

## Results

Each cell shows the three run outcomes. All four routes had complete tick coverage on every run.

| Frozen form | Clean | Defect | Do-nothing | Comment-only |
| --- | --- | --- | --- | --- |
| Left signed travel floor, >75 px | pass / pass / pass | fail / fail / fail | fail / fail / fail | pass / pass / pass |
| Right signed travel floor, >75 px | pass / pass / pass | pass / pass / pass | fail / fail / fail | pass / pass / pass |
| Right-minus-left signed displacement, >150 px | pass / pass / pass | pass / pass / pass | fail / fail / fail | pass / pass / pass |
| Signed displacement equality, ≤2 px | fail / fail / fail | fail / fail / fail | pass / pass / pass | fail / fail / fail |
| Screen range equality, ≤2 px | pass / pass / pass | fail / fail / fail | pass / pass / pass | pass / pass / pass |
| Advisory world-space mirror, ≤2 px | pass / pass / pass | fail / fail / fail | not_exercised / not_exercised / not_exercised | pass / pass / pass |
| Compound diagnostic | pass / pass / pass | fail / fail / fail | fail / fail / fail | pass / pass / pass |

The world-space readings were −100.01 px left and +100.01 px right in every clean run, −50.00 px and +100.01 px in every defect run, and zero in both directions in the frozen-player control. All idle readings were zero. The defect's left travel was 50.0% of its right travel. The right-minus-left check still passed on the defect at 150.01 px. Left and right screen ranges were 5.0 and 5.0 px on clean, 2.5 and 5.0 px on the defect, and zero on both frozen routes. All 12 comment-only traces matched their clean counterparts byte for byte.

The left travel floor cleared its strict bound by 25.01 px in every clean run and missed it by 25.00 px in every defect run. The built-in mirror's clear window was ticks 10–139. Its signed readings were −99.89 and +99.89 px on clean and −49.88 and +99.89 px on the defect. Clean anti-symmetry cleared the fixed 2 px tolerance by 2.00 px, the tightest positive clean clearance among the tested checks. The frozen mirror saw zero motion with both the recorded and grounded floor states. Its 8 px minimum activity gives an indeterminate control result. The signed floors give the compound diagnostic a decisive control failure.

The left floor is the only ordinary proposal that passes legacy `assess.validity` against the defect as the base near miss. It passed clean 3/3, failed the defect 3/3, and decisively failed the frozen-player control 3/3. The experiment's comment-only arm also passed 3/3. The floor detects a calibrated leftward deficit on this probe. Its comparator reads left travel against an idle probe with a fixed threshold, so the outcome gives no dynamic comparison with rightward travel. The current gate relevance map has no `player_dx_px` binding and returns false for this report and predicate.

The ordinary trace proposal language has a cross-probe relation over one raw signed signal and a same-probe comparison of two signals. It has no cross-probe magnitude transform or conjunction. Screen-range equality catches the defect but is discarded because it passes the frozen-player control. The stock mirror incorporates the negation transform and can also pass if both requested directions are swapped. Legacy validity allows its indeterminate control result, while the generator places its rows in the advisory mirror stage. The compound diagnostic checks both requested directions and compares magnitudes using existing predicates. The generator cannot retain this compound as one model proposal.

The harness ran Godot `4.7.2.stable.official.ed1daf0bf`. It used fresh game copies and its environment allowlist. Its automatic isolation fell back to the host because bubblewrap could not set a UID map on the read-only filesystem. This local measurement did not produce a stock reproduction score record, which also requires the defect-plus-no-fix arm.
