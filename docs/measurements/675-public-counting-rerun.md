# The public counting audit, re-run with #675's controls

Re-run on November 20, 2026 at main `da633d5` plus this change, on the 24 frozen public records of
[run 43465090517](https://github.com/Expectrail/Expectrail/actions/runs/43465090517). Godot
4.7.2.stable.official.ed1daf0bf, headless, locally. No model was called and nothing was dispatched.

- The do-nothing rows come from `tools/do_nothing_public.py` (44 route groups, 132 replays, 9 min 52 s). Its
  counts are the same as the [November measurement](675-do-nothing-control.md): 56 pass, 35 fail,
  33 indeterminate and 11 not run of the 135 checks on the reference, and 41 of the 91 legacy-kept checks
  pass the control.
- The audit ran twice, with the harmless control each time (about 11 minutes each). Both runs gave the same
  harmless rows. The second run's page is below.
- **The replays here were not sandboxed.** This machine has no bubblewrap ("sandbox mode auto, tool none"
  below). The game is the bundled public platformer and the patches are the public controls.
- **11 checks were not run** on either control. They use model-proposed routes that are only in the run's
  artifacts. This session's network could not reach the artifact host, so they were not downloaded. With
  them in `jit-routes` beside each record, both controls run those checks
  ([how](675-harmless-control.md#reproduce-the-measured-route-set)).

Commands:

```sh
python3 tools/do_nothing_public.py --work /tmp/dn --out /tmp/do-nothing.md
python3 -m expectrail.jit.counting public-bench \
  --records bench/jit/recordings/public-43465090517/repro \
  --harmless-work /tmp/harmless --do-nothing-rows /tmp/dn/rows.json --out page.md
```

The page the audit wrote:

## Offline counting audit of the public reproduction bench (#271)

The counting assessment uses existing records. The separate harmless control replays the clean game and its comment-only edit. No trusted source certificate/context is supplied.
Every legacy record is advisory: candidate shown, no authenticated trusted producer/replayer, and no per-arm coverage provenance.
This is not the rate of a new candidate-withheld, trusted generation run.

| Public defect | Checks assessed | Counting | Advisory | Canonical run SHA-256 |
| --- | ---: | ---: | ---: | --- |
| air-jump | 6 | 0 | 6 | `566e03f7ba8eebe2e7e89d8feb8e9a3ce1d75b75ea6e24db568642c950fb5873` |
| gun-cooldown | 6 | 0 | 6 | `fb829788967783f6604e68a8c0e17c87ad396352d0ebd1a0d9d7ded11ec2825c` |
| body-flip | 7 | 0 | 7 | `b12f1d649e7e7ee87468e17053f3633e8064215da1c6eac005c070aff6b07ed6` |
| enemy-ledge | 6 | 0 | 6 | `d0e2b725d11cc8bc812920d1a61d2ace03bac9c5c44d79269b8a5f94eb1d5029` |
| bullet-through-enemy | 4 | 0 | 4 | `69def49303f002744806103716f84c217106804b13146a14830e29d1053d9cb7` |
| platforms-not-solid | 5 | 0 | 5 | `1308f90301e9bdb1922518ee4aca0ce1dc4be72cd55a159f2186c3bcbe1f58bd` |
| floaty-fall | 5 | 0 | 5 | `0825d03479081dcbb4717440cf67afa69bee71fa5f3f1e0415e127ce2ec84db8` |
| jump-always-full | 6 | 0 | 6 | `e9d520cc8bf36821aaaf7afc395cc891c88413b0a37093bbb104d672e75ad69e` |
| slow-left | 5 | 0 | 5 | `30c16f8aa65df59e827ff0807701a050c6e2d7a95292ee83120d5ee5a2abdc72` |
| slides-after-stop | 6 | 0 | 6 | `ff459eb78e2c88d062872eefddc3c64f2e557f2def4805ab150c65ebec55063c` |
| no-shooting-in-air | 2 | 0 | 2 | `7678076a41d702bf43bf6af8d1aaf22a08011875bd549151aa874aa182810699` |
| jump-needs-rest | 8 | 0 | 8 | `9d311d65863937c89bab6e145f1b0a7a709faafd3478e9c5727110ad90043e42` |
| double-jump-once | 4 | 0 | 4 | `76cfe2f44c6af57a74050479164367cd29f1de23eaac8889ee5c7de4f227cdf4` |
| coin-stays | 7 | 0 | 7 | `315af52fda380f11c55eea4e25a48ad384cf61454bf8bfa4dae4e53aaf0be429` |
| coin-counts-twice | 6 | 0 | 6 | `c53dea5d49601281ee295804742cd80ba1d041a384dc9db7f65628733ecf314c` |
| coin-counter-stuck | 6 | 0 | 6 | `db8b56947ead3ecf755127a7289495e1aa847ea268e3ff2b5c487502a48dfdfb` |
| gun-cooldown-long | 6 | 0 | 6 | `71422060abf6deb80e31af412014eebb2006cd654ad615bb7ff5308f3bbecd43` |
| enemy-missing | 6 | 0 | 6 | `08df13d01bd2330e8dca256a122b7c3289c22acd88612377db5055a364a2a82e` |
| enemy-fast-left | 6 | 0 | 6 | `bba25a959dd108ff5d67b1361884d8c70a1640c80b5171d5306c03153f721f9b` |
| enemy-slides-when-shot | 4 | 0 | 4 | `78fffb502c3049db07a9733bdfe960d49b5e396be99dd651f1e51dfda3f0dd03` |
| enemy-walks-backwards | 6 | 0 | 6 | `da6b7e57c98a443d9ca01365937b6d0f148f837c3b5e0f05280cd4b3dc333a0e` |
| camera-stops-right | 6 | 0 | 6 | `1dd10e5dce95df87bb36d57757b0c96a81ae77cc367dad3fedbbf4ed0a11a495` |
| camera-cut-top | 6 | 0 | 6 | `c5485b94b25e02a41f02fc9c9118fe5add11e2ff90b02d14bdbc96d3a5cc5229` |
| bullet-behind-scenery | 8 | 0 | 8 | `462729b751eca29347a139d20c435594a1aa37f32c0ff90fd4a34963355af040` |

Total: 24 public defects; 137 checks assessed; 0 counting; 137 advisory.

Of these, 91 are recorded as valid by the legacy keep rule; 46 are dropped proposals retained only as advisory diagnostics. The counting classification used the frozen outcomes.

### Do-nothing control (#675)

A check that still passes when the actor it is about does nothing states no obligation, and the generator now drops it. These columns apply that rule to the frozen records, from the control's own replays (`tools/do_nothing_public.py`). A row is used only when it names this record and this exact check by digest; otherwise the check is "cannot tell", neither kept nor dropped. Advisory: the counting classification above is unchanged.

| Public defect | Legacy kept | Dropped by the control | Cannot tell | Kept | Legacy catches | Catches kept |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| air-jump | 6 | 6 | 0 | 0 | 6 | 0 |
| gun-cooldown | 6 | 2 | 0 | 4 | 6 | 4 |
| body-flip | 7 | 2 | 0 | 5 | 7 | 5 |
| enemy-ledge | 6 | 6 | 0 | 0 | 6 | 0 |
| bullet-through-enemy | 4 | 0 | 0 | 4 | 4 | 4 |
| platforms-not-solid | 5 | 0 | 0 | 5 | 5 | 5 |
| floaty-fall | 5 | 3 | 0 | 2 | 5 | 2 |
| jump-always-full | 6 | 0 | 0 | 6 | 6 | 6 |
| slow-left | 5 | 5 | 0 | 0 | 5 | 0 |
| slides-after-stop | 6 | 6 | 0 | 0 | 6 | 0 |
| no-shooting-in-air | 1 | 0 | 0 | 1 | 1 | 1 |
| jump-needs-rest | 8 | 5 | 0 | 3 | 8 | 3 |
| double-jump-once | 4 | 0 | 0 | 4 | 4 | 4 |
| coin-stays | 0 | 0 | 0 | 0 | 0 | 0 |
| coin-counts-twice | 0 | 0 | 0 | 0 | 0 | 0 |
| coin-counter-stuck | 0 | 0 | 0 | 0 | 0 | 0 |
| gun-cooldown-long | 6 | 0 | 0 | 6 | 6 | 6 |
| enemy-missing | 6 | 0 | 0 | 6 | 6 | 6 |
| enemy-fast-left | 6 | 6 | 0 | 0 | 6 | 0 |
| enemy-slides-when-shot | 4 | 0 | 0 | 4 | 4 | 4 |
| enemy-walks-backwards | 0 | 0 | 0 | 0 | 0 | 0 |
| camera-stops-right | 0 | 0 | 0 | 0 | 0 | 0 |
| camera-cut-top | 0 | 0 | 0 | 0 | 0 | 0 |
| bullet-behind-scenery | 0 | 0 | 0 | 0 | 0 | 0 |

Total: 91 legacy kept; 41 dropped by the control; 0 cannot tell; 50 kept. Catches: 91 recorded, 41 dropped, 0 cannot tell, 50 kept.

Control outcomes over all bound checks: 56 passes, 35 fails, 35 indeterminate, 11 not run.

Of the 50 kept, 24 fail the control (the check is shown to state an obligation), 22 are indeterminate and 4 were not run on it: the control cannot drop those, and it does not show they state one.

Public defects whose every recorded catch is dropped: `air-jump`, `enemy-ledge`, `slow-left`, `slides-after-stop`, `enemy-fast-left`.

### Metamorphic checks

Metamorphic rows in these records: 0. They are advisory: a record keeps them apart from `proposed`, `validity` and `catches`, and this audit never assesses them for counting.

### Harmless control on the clean platformer

The registered comment-only operator adds one comment in `player/player.gd`. Each available trace check uses three fresh clean replays and three with the patch. The results measure this source edit only. All rows are advisory.

Recorded headless engine and isolation: 4.7.2.stable.official.ed1daf0bf, sandbox mode auto, tool none.

Clean source tree `c2513cb02908c016020205df272f5ff9e3be8cbf6272f41fffd7e0030691a9ba`. Patch SHA-256 `48a16859864aa88fdbfd94bb0a508b9764bacf19fb6ef53def4d6f9b22b16b65`.

| Public defect | Check | Clean repetitions | Changed repetitions | Outcome |
| --- | --- | --- | --- | --- |
| air-jump | `jit-c1` | pass, pass, pass | pass, pass, pass | pass |
| air-jump | `jit-c2` | pass, pass, pass | pass, pass, pass | pass |
| air-jump | `jit-c3` | pass, pass, pass | pass, pass, pass | pass |
| air-jump | `jit-c4` | pass, pass, pass | pass, pass, pass | pass |
| air-jump | `jit-c5` | pass, pass, pass | pass, pass, pass | pass |
| air-jump | `jit-c6` | pass, pass, pass | pass, pass, pass | pass |
| gun-cooldown | `jit-cooldown-interval-right` | pass, pass, pass | pass, pass, pass | pass |
| gun-cooldown | `jit-cooldown-interval-left` | pass, pass, pass | pass, pass, pass | pass |
| gun-cooldown | `jit-cooldown-count-right-eq` | pass, pass, pass | pass, pass, pass | pass |
| gun-cooldown | `jit-cooldown-count-left-eq` | pass, pass, pass | pass, pass, pass | pass |
| gun-cooldown | `jit-cooldown-gap-right-eq` | pass, pass, pass | pass, pass, pass | pass |
| gun-cooldown | `jit-cooldown-gap-left-eq` | pass, pass, pass | pass, pass, pass | pass |
| body-flip | `jit-face-hold-left` | pass, pass, pass | pass, pass, pass | pass |
| body-flip | `jit-face-reverse` | pass, pass, pass | pass, pass, pass | pass |
| body-flip | `jit-face-move-fire-left` | pass, pass, pass | pass, pass, pass | pass |
| body-flip | `jit-face-jump-left` | pass, pass, pass | pass, pass, pass | pass |
| body-flip | `jit-sym-flips-hold` | pass, pass, pass | pass, pass, pass | pass |
| body-flip | `jit-sym-flips-shoot` | pass, pass, pass | pass, pass, pass | pass |
| body-flip | `jit-sym-mismatch-jump` | pass, pass, pass | pass, pass, pass | pass |
| enemy-ledge | `jit-e1` | pass, pass, pass | pass, pass, pass | pass |
| enemy-ledge | `jit-e2` | pass, pass, pass | pass, pass, pass | pass |
| enemy-ledge | `jit-e3` | pass, pass, pass | pass, pass, pass | pass |
| enemy-ledge | `jit-e4` | pass, pass, pass | pass, pass, pass | pass |
| enemy-ledge | `jit-e5` | pass, pass, pass | pass, pass, pass | pass |
| enemy-ledge | `jit-e6` | pass, pass, pass | pass, pass, pass | pass |
| bullet-through-enemy | `jit-c1-kill-count` | pass, pass, pass | pass, pass, pass | pass |
| bullet-through-enemy | `jit-c2-extent-move` | pass, pass, pass | pass, pass, pass | pass |
| bullet-through-enemy | `jit-c3-extent-shoot48` | pass, pass, pass | pass, pass, pass | pass |
| bullet-through-enemy | `jit-c4-extent-shoot12` | pass, pass, pass | pass, pass, pass | pass |
| platforms-not-solid | `jit-c1-landing-sooner-base` | pass, pass, pass | pass, pass, pass | pass |
| platforms-not-solid | `jit-c2-landing-sooner-w40` | pass, pass, pass | pass, pass, pass | pass |
| platforms-not-solid | `jit-c3-landing-sooner-w80` | pass, pass, pass | pass, pass, pass | pass |
| platforms-not-solid | `jit-r-jit-c4-repl-38` | — | — | not-run (missing exact route jit-r-jit-left38-dbl) |
| platforms-not-solid | `jit-r-jit-c5-repl-42` | — | — | not-run (missing exact route jit-r-jit-left42-dbl) |
| floaty-fall | `jit-check-w0-single-double` | pass, pass, pass | pass, pass, pass | pass |
| floaty-fall | `jit-check-w40-single-double` | pass, pass, pass | pass, pass, pass | pass |
| floaty-fall | `jit-check-w80-single-double` | pass, pass, pass | pass, pass, pass | pass |
| floaty-fall | `jit-check-w0-double-multi` | pass, pass, pass | pass, pass, pass | pass |
| floaty-fall | `jit-check-w40-double-multi` | pass, pass, pass | pass, pass, pass | pass |
| jump-always-full | `jit-tap-low-w0` | pass, pass, pass | pass, pass, pass | pass |
| jump-always-full | `jit-tap-low-w80` | pass, pass, pass | pass, pass, pass | pass |
| jump-always-full | `jit-tap-low-l40` | pass, pass, pass | pass, pass, pass | pass |
| jump-always-full | `jit-double-higher-w40` | pass, pass, pass | pass, pass, pass | pass |
| jump-always-full | `jit-hold-higher-than-tap` | — | — | not-run (missing exact route jit-short-tap) |
| jump-always-full | `jit-tap-low-w120` | pass, pass, pass | pass, pass, pass | pass |
| slow-left | `jit-c4` | pass, pass, pass | pass, pass, pass | pass |
| slow-left | `jit-c5` | pass, pass, pass | pass, pass, pass | pass |
| slow-left | `jit-r-jit-d1` | pass, pass, pass | pass, pass, pass | pass |
| slow-left | `jit-r-jit-d2` | pass, pass, pass | pass, pass, pass | pass |
| slow-left | `jit-r-jit-d3` | pass, pass, pass | pass, pass, pass | pass |
| slides-after-stop | `jit-c1` | pass, pass, pass | pass, pass, pass | pass |
| slides-after-stop | `jit-c2` | pass, pass, pass | pass, pass, pass | pass |
| slides-after-stop | `jit-c3` | pass, pass, pass | pass, pass, pass | pass |
| slides-after-stop | `jit-c4` | pass, pass, pass | pass, pass, pass | pass |
| slides-after-stop | `jit-c5` | pass, pass, pass | pass, pass, pass | pass |
| slides-after-stop | `jit-c6` | pass, pass, pass | pass, pass, pass | pass |
| no-shooting-in-air | `jit-c4` | — | — | not-run (missing exact route jit-ground-shoot-1) |
| no-shooting-in-air | `jit-c5` | — | — | not-run (missing exact route jit-air-shoot-1) |
| jump-needs-rest | `jit-c1` | pass, pass, pass | pass, pass, pass | pass |
| jump-needs-rest | `jit-c2` | pass, pass, pass | pass, pass, pass | pass |
| jump-needs-rest | `jit-c3` | pass, pass, pass | pass, pass, pass | pass |
| jump-needs-rest | `jit-c4` | pass, pass, pass | pass, pass, pass | pass |
| jump-needs-rest | `jit-c5` | pass, pass, pass | pass, pass, pass | pass |
| jump-needs-rest | `jit-c6` | pass, pass, pass | pass, pass, pass | pass |
| jump-needs-rest | `jit-c7` | pass, pass, pass | pass, pass, pass | pass |
| jump-needs-rest | `jit-c8` | pass, pass, pass | pass, pass, pass | pass |
| double-jump-once | `jit-c1` | pass, pass, pass | pass, pass, pass | pass |
| double-jump-once | `jit-c2` | pass, pass, pass | pass, pass, pass | pass |
| double-jump-once | `jit-c3` | pass, pass, pass | pass, pass, pass | pass |
| double-jump-once | `jit-c4` | pass, pass, pass | pass, pass, pass | pass |
| coin-stays | `jit-r-jump-double-higher-w40` | pass, pass, pass | pass, pass, pass | pass |
| coin-stays | `jit-r-jump-eight-capped-w40` | pass, pass, pass | pass, pass, pass | pass |
| coin-stays | `jit-r-cooldown-limits-left` | pass, pass, pass | pass, pass, pass | pass |
| coin-stays | `jit-r-rapid-press-same-left` | pass, pass, pass | pass, pass, pass | pass |
| coin-stays | `jit-r-facing-follows-hold-right` | pass, pass, pass | pass, pass, pass | pass |
| coin-stays | `jit-r-enemies-dont-fall-hold-right` | pass, pass, pass | pass, pass, pass | pass |
| coin-stays | `jit-r-enemies-patrol-wait-long` | pass, pass, pass | pass, pass, pass | pass |
| coin-counts-twice | `jit-r-reg-double-higher-w40` | pass, pass, pass | pass, pass, pass | pass |
| coin-counts-twice | `jit-r-reg-no-triple-rise-w80` | pass, pass, pass | pass, pass, pass | pass |
| coin-counts-twice | `jit-r-reg-cooldown-left` | pass, pass, pass | pass, pass, pass | pass |
| coin-counts-twice | `jit-r-reg-facing-hold-right` | pass, pass, pass | pass, pass, pass | pass |
| coin-counts-twice | `jit-r-reg-enemy-no-fall-left` | pass, pass, pass | pass, pass, pass | pass |
| coin-counts-twice | `jit-r-reg-enemy-present-hold` | pass, pass, pass | pass, pass, pass | pass |
| coin-counter-stuck | `jit-r-jit-double-rise-b` | pass, pass, pass | pass, pass, pass | pass |
| coin-counter-stuck | `jit-r-jit-jump-limit-b` | pass, pass, pass | pass, pass, pass | pass |
| coin-counter-stuck | `jit-r-jit-cooldown-left` | pass, pass, pass | pass, pass, pass | pass |
| coin-counter-stuck | `jit-r-jit-facing-left` | pass, pass, pass | pass, pass, pass | pass |
| coin-counter-stuck | `jit-r-jit-patrol-drop-b` | pass, pass, pass | pass, pass, pass | pass |
| coin-counter-stuck | `jit-r-jit-patrol-motion-b` | pass, pass, pass | pass, pass, pass | pass |
| gun-cooldown-long | `jit-c1` | pass, pass, pass | pass, pass, pass | pass |
| gun-cooldown-long | `jit-c2` | pass, pass, pass | pass, pass, pass | pass |
| gun-cooldown-long | `jit-c3` | pass, pass, pass | pass, pass, pass | pass |
| gun-cooldown-long | `jit-c4` | pass, pass, pass | pass, pass, pass | pass |
| gun-cooldown-long | `jit-c5` | pass, pass, pass | pass, pass, pass | pass |
| gun-cooldown-long | `jit-c6` | pass, pass, pass | pass, pass, pass | pass |
| enemy-missing | `jit-c3` | pass, pass, pass | pass, pass, pass | pass |
| enemy-missing | `jit-c4` | pass, pass, pass | pass, pass, pass | pass |
| enemy-missing | `jit-c5` | pass, pass, pass | pass, pass, pass | pass |
| enemy-missing | `jit-c6` | pass, pass, pass | pass, pass, pass | pass |
| enemy-missing | `jit-r-jit-c7` | pass, pass, pass | pass, pass, pass | pass |
| enemy-missing | `jit-r-jit-c8` | pass, pass, pass | pass, pass, pass | pass |
| enemy-fast-left | `jit-enemy-extent-long-vs-short-right` | pass, pass, pass | pass, pass, pass | pass |
| enemy-fast-left | `jit-enemy-extent-long-vs-short-left` | pass, pass, pass | pass, pass, pass | pass |
| enemy-fast-left | `jit-enemy-extent-long-vs-reverse` | pass, pass, pass | pass, pass, pass | pass |
| enemy-fast-left | `jit-r-jit-enemy-extent-long-vs-shoot-right` | pass, pass, pass | pass, pass, pass | pass |
| enemy-fast-left | `jit-r-jit-enemy-extent-long-vs-jump-short` | pass, pass, pass | pass, pass, pass | pass |
| enemy-fast-left | `jit-r-jit-enemy-extent-long-vs-movefire-right` | pass, pass, pass | pass, pass, pass | pass |
| enemy-slides-when-shot | `jit-c1` | pass, pass, pass | pass, pass, pass | pass |
| enemy-slides-when-shot | `jit-c2` | pass, pass, pass | pass, pass, pass | pass |
| enemy-slides-when-shot | `jit-c3` | pass, pass, pass | pass, pass, pass | pass |
| enemy-slides-when-shot | `jit-c4` | pass, pass, pass | pass, pass, pass | pass |
| enemy-walks-backwards | `jit-enemy-faces-travel-wait` | insufficient_observation, insufficient_observation, insufficient_observation | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate |
| enemy-walks-backwards | `jit-enemy-faces-travel-right` | pass, pass, pass | pass, pass, pass | pass |
| enemy-walks-backwards | `jit-enemy-faces-travel-left` | pass, pass, pass | pass, pass, pass | pass |
| enemy-walks-backwards | `jit-enemy-faces-travel-reverse` | pass, pass, pass | pass, pass, pass | pass |
| enemy-walks-backwards | `jit-enemy-faces-travel-shootr` | insufficient_observation, insufficient_observation, insufficient_observation | insufficient_observation, insufficient_observation, insufficient_observation | indeterminate |
| enemy-walks-backwards | `jit-enemy-faces-travel-shootl` | pass, pass, pass | pass, pass, pass | pass |
| camera-stops-right | `jit-r-far-e1` | — | — | not-run (missing exact route jit-r-far-right-8s) |
| camera-stops-right | `jit-r-far-e2` | — | — | not-run (missing exact route jit-r-far-right-12s) |
| camera-stops-right | `jit-r-far-e3` | — | — | not-run (missing exact route jit-r-far-right-12s) |
| camera-stops-right | `jit-r-far-e6` | — | — | not-run (missing exact route jit-r-far-right-single) |
| camera-stops-right | `jit-r-far-e7` | — | — | not-run (missing exact route jit-r-far-right-double) |
| camera-stops-right | `jit-r-far-e8` | — | — | not-run (missing exact route jit-r-far-right-double) |
| camera-cut-top | `jit-c1-double-higher` | pass, pass, pass | pass, pass, pass | pass |
| camera-cut-top | `jit-c2-only-one-air-jump` | pass, pass, pass | pass, pass, pass | pass |
| camera-cut-top | `jit-c3-cooldown-limits` | pass, pass, pass | pass, pass, pass | pass |
| camera-cut-top | `jit-c4-facing` | pass, pass, pass | pass, pass, pass | pass |
| camera-cut-top | `jit-c5-no-fall` | pass, pass, pass | pass, pass, pass | pass |
| camera-cut-top | `jit-c6-patrol-moves` | pass, pass, pass | pass, pass, pass | pass |
| bullet-behind-scenery | `jit-r-jit-d1` | pass, pass, pass | pass, pass, pass | pass |
| bullet-behind-scenery | `jit-r-jit-d2` | pass, pass, pass | pass, pass, pass | pass |
| bullet-behind-scenery | `jit-r-jit-d3` | pass, pass, pass | pass, pass, pass | pass |
| bullet-behind-scenery | `jit-r-jit-d4` | pass, pass, pass | pass, pass, pass | pass |
| bullet-behind-scenery | `jit-r-jit-d5` | pass, pass, pass | pass, pass, pass | pass |
| bullet-behind-scenery | `jit-r-jit-d6` | pass, pass, pass | pass, pass, pass | pass |
| bullet-behind-scenery | `jit-r-jit-d7` | pass, pass, pass | pass, pass, pass | pass |
| bullet-behind-scenery | `jit-r-jit-d8` | pass, pass, pass | pass, pass, pass | pass |

124 pass, 0 false-rejection, 2 indeterminate, 11 not-run.
