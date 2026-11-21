# Air jump

The player must launch from the ground and respond to one additional jump press in the same airborne span. A third jump before landing is the counterexample. The proposal uses the public report, the clean game, and the existing GoDL probes and trace operators. It was frozen before the defect replay under `signals-reach-evidence-menu-control` with the candidate withheld. [Frozen proposal](jit-proposal.json) · [SHA-256](SHA256SUMS)

## Routes and measurements

The three stock `jump-l40` probes are identical in `baseline` and `signals-reach-evidence-menu-control`. They start by walking left for 40 ticks and waiting 10 ticks. Their jump press schedules are `60`, `60, 80`, and `60, 80, 100, 120, 140, 160, 180, 200`. The compiled windows are 140, 160, and 280 ticks. The count comparisons use zero tolerance. A clean scout measured 113.61 px on the eight-press route before freezing the exploratory 125 px rise cap. The custom GoDL twin uses the stock two-press route and holds the second press for eight ticks instead of four. Its window remains 160 ticks.

For the stock eight-press route, the player is grounded at tick 60 and rises 5.965 px at takeoff on tick 61. The second press produces an upward kick at tick 81. The third press occurs at tick 100, within that first flight in both builds. At tick 101 the per-tick vertical displacement changes by +0.146 px on clean and −4.954 px on the defect. The stock signal counts a change below −0.5 px as a kick. The clean flight ends at tick 119 and the defect flight ends at tick 270. The stock signal reads one and seven additional jumps respectively.

## Outcomes

Each cell lists repetitions 1, 2 and 3. P is a decisive pass, F a decisive fail and I an indeterminate control from `not_exercised`.

| Proposed check | Clean | Defect | Frozen | Clean plus comment | Stock replay assessor |
| --- | --- | --- | --- | --- | --- |
| Stock count demand, eight presses > one | P P P | P P P | F F F | P P P | Drops, defect survives |
| Stock count ceiling, eight presses ≤ two | P P P | F F F | P P P | P P P | Drops, frozen player passes |
| Stock eight-press route, 125 px rise cap | P P P | F F F | I I I | P P P | Keeps, frozen result is indeterminate |
| Custom GoDL twin, two presses with the longer hold rise higher than eight short presses | P P P | F F F | F F F | P P P | Keeps, with decisive frozen rejection |
| Manual conjunction of the stock demand and ceiling | P P P | F F F | F F F | P P P | External calculation |

| Route | Clean count / rise | Defect count / rise | Frozen count / rise | Clean plus comment count / rise |
| --- | ---: | ---: | ---: | ---: |
| Stock one press | 0 / 57.93 px | 0 / 57.93 px | 0 / 0 px | 0 / 57.93 px |
| Stock two presses | 1 / 113.46 px | 1 / 113.46 px | 0 / 0 px | 1 / 113.46 px |
| Stock eight presses | 1 / 113.61 px | 7 / 424.49 px | 0 / 0 px | 1 / 113.61 px |
| Custom twin | 1 / 126.56 px | 1 / 126.56 px | 0 / 0 px | 1 / 126.56 px |

Each route produced identical trace hashes across its three repetitions in each arm. The comment-only traces matched the corresponding clean traces. The tightest clean count clearance is zero at the allowable count of one, one jump below the first violation. The stock height cap has 11.39 px clearance on clean, and the custom strict height comparison has 12.95 px.

The stock count checks split the obligation across two rows. The demand rejects the frozen player, and the ceiling rejects the defect. The generator qualifies each row individually. The proposal reader rejected an `all_of` operation containing the two stock relations. The custom height relation is a supported single check with decisive outcomes in all arms. Its predicate is relative height, and it can pass if only the twin rises. The stock rise cap checks height when it observes an anchored airborne span, so the frozen run has no span to evaluate. The replay assessor allows that indeterminate outcome. The exact count conjunction remains an advisory calculation.

One frozen proposal was replayed. Candidate testing, model generation, reproduction scoring, pixel observation and the full test suite were outside the measurement.

## Reproduction

Run from a checkout containing this case. The measured product source was `d5b1e8f4016f69fd7285d1ec664ac695da1d465d`. The engine reports `4.7.2.stable.official.ed1daf0bf` and has SHA-256 `8d106cbe6144c2dc7e881d61d2429c1a8a76e6b22ef48bd5e48dcf934953f71e`. The measured interpreter was Python 3.13.5.

```sh
(cd bench/jit/ceiling/762/air-jump && sha256sum -c SHA256SUMS)
AIR_JUMP_WORK=$(mktemp -d /tmp/expectrail-762-air-jump.XXXXXX)
PYTHONPATH="$PWD" python3 \
  bench/jit/ceiling/762/air-jump/replay.py \
  --godot "$EXPECTRAIL_GODOT" \
  --work "$AIR_JUMP_WORK"
```

The runner passes the public defect patch to the harness by path, creates the standard `do-nothing:player` patch from the clean game, and applies the registered comment-only operator to a clean copy. It records the original trace, replay metadata and `results.json` in the work directory. It uses the stock evaluator, control judge and per-check replay assessor after collecting all three repetitions in every arm, including rows the generator would stop early. The engine ran on copied game trees with the harness's allowlisted environment. The harness recorded that bubblewrap could not set up its UID map on the read-only filesystem and fell back to the host filesystem, network and processes. [Replay source](replay.py)
