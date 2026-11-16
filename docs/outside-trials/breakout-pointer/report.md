# Breakout after pointer/menu support

The same [MIT-licensed game](https://github.com/mike0697/Breakout/tree/0ac7aed444ea593a023d9b666c211d7ab8acd51e), by Michele Pizzeghello, now starts a round and moves its paddle using configuration and a generated route. The original [choice, made before onboarding](original-choice.json), was retained; no easier replacement was chosen. This follows the [earlier failed trial](../breakout/report.md).

The product was frozen before this trial. [Checksums](core-unchanged.json) confirm 307 core files stayed unchanged and all 105 tracked files of the pinned game stayed unchanged. Only config, routes, draft checks and the two existing seeded patches were supplied. No approval or live model request was made.

## What happened

`inspect` found a pointer read in `scripts/paddle.gd` and two possible bodies, Paddle and Ball. `init` asked the harness for live controls at tick 9. It found the enabled Start button at `UI/GameMenu/CenterContainer/VBoxContainer/Start`, connected through `pressed` to `GameManager:_on_start_pressed`, and measured its centre at viewport `[180, 290]`. The generated route moves there at tick 12, presses at 13 and releases at 14, then sweeps the pointer across the viewport. The user configuration binds Paddle as player and Ball as ball, using their own art. The route has 407 ticks, seed 1, and no pause action.

The auto-route command made three identical headless traces and reported movement. Three additional rendered captures were also byte-identical. Each pinned capture has 70 distinct paddle positions. The harmless trace matches the pinned trace byte for byte. These are finite recorded runs of this seed, not proof of determinism for all inputs or platforms. [Measured results](results.json), [commands and stops](commands.md), [route and config](../../../tests/outside/breakout-pointer/).

## Results: drafts stay drafts

| Copy | CLI verify | Approved checks run | Paddle bounds, raw draft engine diagnostic | Ball starts, raw draft engine diagnostic |
| --- | --- | ---: | --- | --- |
| Pinned | needs-review | 0 | pass, 51 frames | pass, 11 frames |
| Harmless comment | needs-review | 0 | pass, 51 frames | pass, 11 frames |
| Broken: force paddle x=8 | needs-review | 0 | fail, first checked frame 20, all 51 checked frames | pass, 11 frames |

[CLI outputs](trial-logs/12-verify-pinned.log), [harmless](trial-logs/13-verify-harmless.log), [broken](trial-logs/14-verify-broken.log) explicitly say no checks ran, the config is a draft, and vision did not run. The separate raw diagnostics use the existing engine observation converter and evaluator; **they are not gate rejects or accepts**. The broken box at the first checked frame is `[-15.5, 607, 31.5, 625]`, outside `[0, 0, 360, 640]`. Frame 20 is the beginning of the declared check window, not a claim that this is the first bad tick in the whole replay.

The draft bounds check covers frames 20..70 and requires a left-lane checkpoint. The draft ball check covers frames 40..50 and requires the same checkpoint. Sean would be approving the selected roles/art boxes, start click, route, windows, region and source-derived timing assumption. This trial does not approve them. It does not claim ball physics, score, all bricks, all routes, late-game play, vision agreement or a verified outside-project accept.

## Stops and limitations

1. One operator command used `python3 -m expectrail`, which has no module entry point. The corrected `python3 -m expectrail.cli` worked. Both attempts are logged.
2. Doctor found low disk space. Its suggested `TMPDIR` and `EXPECTRAIL_TOOLS` settings moved scratch work to memory-backed storage. Bubblewrap could not create its uid map, so these were explicitly diagnostic, non-isolated runs. No keys/caps were provided. Godot 4.7.2 and an Xvfb display were available; the renderer was llvmpipe LLVM 19.1.7.
3. Paddle/Ball required a human binding choice; static inspect continues to list both candidates. The explicit config chooses the replay role.
4. Auto-route output lists hundreds of pointer events. It needs a concise sweep summary; no core change was made during the trial.
5. The outside-trial registry still refuses repository-root `path: "."`. The game was not added to the list. Manual config-only replay succeeded; registry integration did not. [Issue texts](issues.md).

The [frame 40 screenshot](trial-evidence/pinned-1/frame-40.png) shows the round after the menu was dismissed. Screenshots reproduce the game's MIT-licensed art; [licence](LICENSE.txt). No source game was vendored. Human onboarding time was not measured; command machine times and every stop are recorded in [commands.md](commands.md).
