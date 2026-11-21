# Reproduction ceiling on three public reports (#762)

The question is whether a person can write a check for each report using the generator's current
probe library and check language. A successful check has to pass clean and comment-only, reject
the public defect, and give a decisive failure on the do-nothing control. Each arm uses three
replays. An indeterminate control leaves the obligation unproven.

We wrote the English obligations on #762 before authoring JSON. The three replay jobs then ran
independently against the same public source revision, `d5b1e8f`, and pinned Godot 4.7.2. Authors
used the report, clean game, probe library and supported predicate code. They froze each first
attempt before running the public patch and used the patch by path. The historical baseline
proposals and candidate material were out of scope for this experiment.
[English obligations and claim](https://github.com/Expectrail/Expectrail/issues/762#issuecomment-7067267516)

The jobs completed 156 formal probe replays across the four arms, plus the clean calibration
replays. Round 1 was frozen for each case, and none used its revision. The headless engine used
disposable game copies. Bubblewrap UID setup failed on this host. The result measures advisory
reproduction against the public controls. The stock scorer and hosted release gate were outside
this experiment.

The harmless arms use a comment-only edit on the clean build. Slow-left generated an inert
GDScript comment in its disposable tree. The other two used the registered comment-only patch.

## Slow left

With matched left and right input durations from the same starting conditions, the robot must
travel in each requested direction and the leftward travel should remain comparable to the
rightward travel. About half the rightward distance is a counterexample.

Round 1 used the stock `jump-l40-x1` and `jump-w40-x1` probes for matched 40-tick holds.
The clean world displacements were −100.01 and +100.01 px. The public defect measured −50.00
and +100.01 px. A parser-accepted strict relation required more than 75 px of leftward travel
against idle. Its tightest clean clearance was 25.01 px. The same rule for rightward travel
passed the defect, consistent with the report.

| Round 1 check | Clean | Defect | Frozen player | Comment-only |
| --- | --- | --- | --- | --- |
| Calibrated left-travel floor | Pass 3/3 | Fail 3/3 | Decisive fail 3/3 | Pass 3/3 |
| Advisory dynamic mirror | Pass 3/3 | Fail 3/3 | Indeterminate 3/3 | Pass 3/3 |
| Mirror plus both directional floors, combined by hand | Pass 3/3 | Fail 3/3 | Decisive fail 3/3 | Pass 3/3 |

The generator is the limiting step for reproducing this specific loss of leftward travel. The
native parser and per-check validity rules support a report-specific floor. The floor fixes a
clean-reference distance. The stronger live right-to-left magnitude comparison used a separate
advisory mirror, whose activity guard leaves the frozen run indeterminate. The report-relevance
map also leaves `player_dx_px` advisory for gate counting. None of those limits prevents detection
in the scoped public replay. No revision was needed.
[All forms, clearance, and reproduction](../../bench/jit/ceiling/762/slow-left/README.md)

## Slides after stop

The robot must move while the arrow is held, then settle promptly after release. Travel late
in the no-input tail is the counterexample. The report gives no numeric stopping limit, so a
numeric margin has to be justified by the clean replay.

Round 1 found a probe-library and timing-expression limit. The long stock holds put the
player into terrain before release. In the clean right hold the last held tick moved only
0.223 px and the release tick moved 0.184 px, compared with 2.5 px per tick in the open lane.
The parser forces episode windows. Its `player_dx_px` signal is net displacement, and
`event_response` is tied to projectile spawn. A release-relative settling bound has no
direct operation in this offer.

The same parser accepts bounded author-supplied hold and wait programs. In this wider
diagnostic, both a longer hold with a shorter idle tail and a continuous hold compared
with a split hold required more than 5 px of extra travel on the designated longer-motion
probe. The clean differences were +10 px each, giving 5 px of clearance. The defect reversed
them to −41.40 and −8.50 px. These probes are separate evidence from the stock library.

| Round 1 wider diagnostic | Clean | Defect | Frozen player | Comment-only |
| --- | --- | --- | --- | --- |
| Longer hold with shorter tail | Pass 3/3 | Fail 3/3 | Decisive fail 3/3 | Pass 3/3 |
| Continuous hold versus split hold | Pass 3/3 | Fail 3/3 | Decisive fail 3/3 | Pass 3/3 |
| Same input with longer idle tail, equality | Pass 3/3 | Fail 3/3 | Pass 3/3, discarded | Pass 3/3 |
| Release-relative trace diagnostic | Pass 3/3 | Fail 3/3 | Decisive fail 3/3 | Pass 3/3 |

Both moving builds travelled 176.25 px under input. The clean late-tail range was zero against
a 1 px bound. The defect moved 71.823 px across the same tail and was still moving at the
final tick. The trace therefore contains the decisive evidence. The stock offer lacks a
direct way to assert it, and the two accepted author-supplied comparisons provide indirect
evidence outside the stock-library trial. Their signal remains advisory under the gate
relevance map. No revision was needed for the wider diagnostic.
[Frozen proposal](../../bench/jit/ceiling/762/slides-after-stop/jit-proposal.json) · [Reproduction](../../bench/jit/ceiling/762/slides-after-stop/replay.py)

## Air jump

The player must launch from the ground and receive repeated jump input before landing. The
clean game's mechanic allows one additional jump in a single airborne period. A third jump
before landing is a counterexample. The replay needs evidence for both the motion demand and
the upper bound.

Round 1 used the stock leftward one-, two- and eight-tap probes. Clean and harmless recorded
zero, one and one extra airborne impulse respectively. The defect recorded seven in the
eight-tap probe. The first extra counterexample was the press at tick 100, with the impulse
observed at tick 101. The clean eight-tap route first landed at tick 119. The stock upper
bound of one has zero numerical clearance on clean and one count to the next discrete value.

| Round 1 check | Clean | Defect | Frozen player | Comment-only |
| --- | --- | --- | --- | --- |
| Stock airborne activity demand | Pass 3/3 | Pass 3/3 | Decisive fail 3/3 | Pass 3/3 |
| Stock upper count bound | Pass 3/3 | Fail 3/3 | Pass 3/3, discarded | Pass 3/3 |
| Stock 125 px rise cap | Pass 3/3 | Fail 3/3 | Indeterminate 3/3 | Pass 3/3 |
| Strict relative height with a custom two-press twin | Pass 3/3 | Fail 3/3 | Decisive fail 3/3 | Pass 3/3 |
| Exact activity and bound, combined by hand | Pass 3/3 | Fail 3/3 | Decisive fail 3/3 | Pass 3/3 |

The clean eight-tap rise was 113.61 px, 11.39 px below the stock cap. The wider height proxy
compared the same eight-tap route with a two-press twin whose second hold lasts longer.
Its clean clearance was 12.95 px and the bug rose 424.49 px on the eight-tap route.
Height can also change with gravity or a ceiling. The supported height proxy and the exact
jump-count obligation cover different behaviours.

The recorded jump signal is sufficient for the exact diagnostic. The current proposal schema
allows one operation per check. The stock assessor drops the count bound because the frozen
player satisfies it and drops the demand because it misses the defect. A native `all_of` was
refused. The manual conjunction gives the required four outcomes, which identifies a
check-language limit for the exact obligation. No revision was needed.
[All forms, timing, and reproduction](../../bench/jit/ceiling/762/air-jump/README.md)

## Reproduce

From a checkout containing these case files, use the repository Python dependencies and
set `EXPECTRAIL_GODOT` to the pinned Godot 4.7.2 executable. The measured product source
revision was [d5b1e8f](https://github.com/Expectrail/Expectrail/commit/d5b1e8f4016f69fd7285d1ec664ac695da1d465d).
Each command writes its traces and result record to a separate new output directory.

```sh
work=$(mktemp -d)
export PYTHONPATH=.
export EXPECTRAIL_GODOT
python3 bench/jit/ceiling/762/slow-left/replay.py --out "$work/slow-left"
python3 bench/jit/ceiling/762/slides-after-stop/replay.py --work "$work/slides-after-stop" \
  --godot "$EXPECTRAIL_GODOT" --workers 3
python3 bench/jit/ceiling/762/air-jump/replay.py --work "$work/air-jump" \
  --godot "$EXPECTRAIL_GODOT"
```

## Excluded report

`enemy-ledge` is a demonstrated report limitation. Its entire public report says “Enemy dosent
go forward and backwards as intended.” The intended patrol is recognizable, while the enemy,
turn point and observed failure remain unspecified. The report-time question is **“Which enemy
should turn, where should it turn, and what does it do instead?”** That answer would supply the
obligation before the generator or verifier needs to choose a route or predicate.
[Public report](../../bench/jit/known/enemy-ledge/report.txt) · [Recorded disposition](https://github.com/Expectrail/Expectrail/issues/762#issuecomment-7066841504)

## Ceiling and what to change first

The frozen attempts produced one decisive reproduction with stock-library probes, using the
calibrated left-travel floor. The broader generator interface also accepted custom probes that separated
sliding and infinite jumping, with the proxy limitations above. The raw traces exposed both
late movement and extra jump impulses, so the remaining direct checks are limited by the
current probe and predicate interface. I would first give a single check a way to require
activity and enforce an upper bound on the same observed opportunity, and qualify it against
the frozen and extra-jump replays. Use the left-travel floor as a prompt benchmark and keep
release-relative settling as the next predicate test. The excluded patrol report needs the
developer's answer to the report-time question before either change can help there.
