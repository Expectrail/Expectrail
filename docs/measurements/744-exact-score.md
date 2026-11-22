# Exact pause-menu score on the public route (#744)

The draft checks that `InterfaceLayer/PauseMenu/ColorRect/CoinsCounter/Label` holds exactly 5 at the final tick of `hold-right-then-toggle-pause`. A separate count of the recorded coins must show pickups before the evaluator judges the Label. The frozen-player control tests this requirement with the pause menu open and zero pickups. [Draft check](../../specs/drafts/727/exact-score/checks/pause-menu-score-after-five-pickups.json) · [Public route](../../specs/drafts/727/exact-score/routes/hold-right-then-toggle-pause.json)

## Engine qualification

Each replay recorded all 464 physics ticks and covered the expected observation window. The cells list pickups, terminal Label value, and verdict for each repetition.

| Build | Repetition 1 | Repetition 2 | Repetition 3 |
| --- | --- | --- | --- |
| `clean` | 5, 5, pass | 5, 5, pass | 5, 5, pass |
| `coin-counts-twice` | 5, 10, fail | 5, 10, fail | 5, 10, fail |
| `coin-counter-stuck` | 5, 0, fail | 5, 0, fail | 5, 0, fail |
| `frozen-player` | 0, 0, needs-review | 0, 0, needs-review | 0, 0, needs-review |
| `comment-only` | 5, 5, pass | 5, 5, pass | 5, 5, pass |

Both defects gave a decisive counterexample at tick 463. The frozen-player verdict records zero judged readings and `not_exercised` because no pickups occurred.
Each build produced identical trace bytes in all three repetitions. The comment-only trace also matched clean.

The default two-observer rule still needs supporting visual evidence for a pass. A match on this
engine-only assertion returns needs-review under that rule. A complete, exercised engine mismatch
can still fail. The public check remains a draft for human approval.

The route presses right at tick 10, releases it at 250, and taps pause at ticks 310–314. The engine records ticks 0–463. The first engine-visible Label reading is at tick 310 in all five builds. The four arms with pickups record one disappearance at each of ticks 174, 186, 198, 216, and 240, reducing the tracked coins from 21 to 16. The frozen player remains stationary and the tracked count stays at 21. The trace-derived observation schedule at 60 frames per second represents the final tick as frame 231. The run captured zero PNG frames and evaluated the integer held by the named Label. Rendered glyphs, vision models, and full gate admission are outside this measurement. [Earlier HUD visibility coverage](727-hud-text.md)

## Reproduce

The run used checkout `4d2e095a60b2904aca103285a904c508e81aa0bf` with the #744 changes in the worktree, Python 3.13.5, and Godot `4.7.2.stable.official.ed1daf0bf`. The executable SHA-256 was `8d106cbe6144c2dc7e881d61d2429c1a8a76e6b22ef48bd5e48dcf934953f71e`. The route SHA-256 was `415e205ff9bdca6c708968238f0eba971a7b28a2b431b772b9f5e4f83bbb07d4` and the draft SHA-256 was `ef7f879455c884791641508739929c1f3d144aed1bfb2359761a9f97dfcaad9c`.

```sh
EXPECTRAIL_744_OUT=$(mktemp -d /tmp/expectrail-744-public.XXXXXX)
PYTHONPATH=. python3 bench/jit/744/replay.py \
  --godot "$EXPECTRAIL_GODOT" \
  --out "$EXPECTRAIL_744_OUT"
```

Run from the repository root with the Python dependencies installed and `EXPECTRAIL_GODOT` set
to the pinned executable. The runner writes each replay, trace, and verdict alongside
`qualification.json` in the output directory. The harness recorded that bubblewrap was unavailable
on this machine and reported host filesystem, network, and processes with an allowlisted environment.
[Replay runner](../../bench/jit/744/replay.py)
