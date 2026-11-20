# Harmless control for the public generated checks (#675)

The current clean game and evaluator were taken from Expectrail revision `21c8d0c397268fc819ff971fe6c74f03c7a0c263` with the advisory control changes. The 24 public source records come from [run 43465090517](https://github.com/Expectrail/Expectrail/actions/runs/43465090517). Check IDs can repeat across records. The public defect, canonical run digest in the counting table and check ID identify a row. The audit also exports the complete spec digest, each route digest, outcomes by arm and hashes of the underlying traces in its local `control.json`.

The [registered comment-only operator](../../agents/fixtures/operators/comment-only.patch) adds one GDScript comment to the player's script. The [mutation registration](../../bench/mutation/preregistration.json) calls it good when stacked on a correct undo. This trial applies that same operator directly to a fresh copy of the clean game. On registration baseline `c169a5e0da304773587304ed47bc8aabcec80da7`, the patch SHA-256 is `48a16859864aa88fdbfd94bb0a508b9764bacf19fb6ef53def4d6f9b22b16b65`. The current mutation bench's operator resolver returned that same file and digest. Its operator directory matched the registration's `agents/fixtures/operators` tree pin `75bb41a6a2f8ea6b601011eb2817da0f1365d8685bf8a1cff6b9041a3ec22d7e`, and `wrongFix.commentOnlyLabel` is `good`. The clean comparison has no patches. No defect or candidate patch is applied to either arm.

Each route has three independently launched headless engine replays per arm. Checks can share the same observed route repetitions. Within an arm, incomplete replays or distinct trace digests make the result indeterminate. For a measured pass or false rejection every required probe must satisfy the existing evaluator's coverage, applicability, trigger and evaluation requirements on every repetition. Three clean passes followed by three changed failures constitute a false rejection. A check already failing on clean cannot establish that the edit caused a rejection. Neither this advisory evidence nor its totals enter counting, strong-catch or gate decisions.

**Measured result:** 135 checks passed the control, zero falsely rejected it, two were indeterminate, and zero were unrun. The two enemy-facing checks (`jit-enemy-faces-travel-wait`, `jit-enemy-faces-travel-shootr`) recorded zero triggers and zero evaluations on each arm. All 137 rows and their provenance reproduced from the saved raw replay and trace bytes. The machine-readable control report's file SHA-256 is `576426042410c64d78c2d5cd0b6600b1885f291c2381b068caecae93ba2e4c5b`.

## Reproduce the measured route set

From the Expectrail checkout, make a temporary copy of the committed public records. The command can compile the library routes directly. Four public artifacts provide the 11 generated routes whose programs are absent from the committed records. The reader compares each route's canonical digest with the corresponding probe in its source record before running it.

```sh
work=$(mktemp -d)
cp -R bench/jit/recordings/public-43465090517/repro "$work/records"
for case in camera-stops-right platforms-not-solid jump-always-full no-shooting-in-air; do
  name="jit-repro-$case"
  case "$case" in
    jump-always-full|no-shooting-in-air) name="$name-round1" ;;
  esac
  gh run download 43465090517 --repo Expectrail/Expectrail \
    --name "$name" --dir "$work/artifacts/$case"
  cp -R "$work/artifacts/$case/jit-routes" "$work/records/repro-$case/"
done
python3 -m expectrail.jit.counting public-bench \
  --records "$work/records" --harmless-work "$work/evidence" --out "$work/report.md"
```

| Public source artifact | ZIP SHA-256 | Generated routes |
| --- | --- | ---: |
| [camera-stops-right](https://github.com/Expectrail/Expectrail/actions/runs/43465090517/artifacts/14062370774) | `02f55cb08083b2c3303471ded450ca0ae4dd1254702011c100d823d9abe4ec61` | 4 |
| [platforms-not-solid](https://github.com/Expectrail/Expectrail/actions/runs/43465090517/artifacts/14061093273) | `e649d4452e61ff946528f1fa65301494a0c628d50dd47193118b94a179824204` | 2 |
| [jump-always-full, first round](https://github.com/Expectrail/Expectrail/actions/runs/43465090517/artifacts/14060975551) | `7eded43c524fe316ffd2330138760405ae72efa74e1a11aaeb1c0790cccb0e51` | 2 |
| [no-shooting-in-air, first round](https://github.com/Expectrail/Expectrail/actions/runs/43465090517/artifacts/14060046873) | `f4fe72e95a6bf6f3a4c0767b92950be75f00d60b0f2f7ac5f195e142da2bc4b6` | 3 |

Omitting those four artifacts leaves affected checks explicitly unrun. The optional repeatable `--harmless-defect ID` limits which cases execute while reporting every frozen check. Raw trace and replay manifests are retained under `$work/evidence/<route-digest>/{clean,changed}-{1,2,3}/`. This is one source-only edit on one bundled game's public trace checks. It does not measure responses to visible changes, other benign edits or outside games.

## Historical counting assessment for these same checks

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

## Harmless control on the clean platformer

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
| platforms-not-solid | `jit-r-jit-c4-repl-38` | pass, pass, pass | pass, pass, pass | pass |
| platforms-not-solid | `jit-r-jit-c5-repl-42` | pass, pass, pass | pass, pass, pass | pass |
| floaty-fall | `jit-check-w0-single-double` | pass, pass, pass | pass, pass, pass | pass |
| floaty-fall | `jit-check-w40-single-double` | pass, pass, pass | pass, pass, pass | pass |
| floaty-fall | `jit-check-w80-single-double` | pass, pass, pass | pass, pass, pass | pass |
| floaty-fall | `jit-check-w0-double-multi` | pass, pass, pass | pass, pass, pass | pass |
| floaty-fall | `jit-check-w40-double-multi` | pass, pass, pass | pass, pass, pass | pass |
| jump-always-full | `jit-tap-low-w0` | pass, pass, pass | pass, pass, pass | pass |
| jump-always-full | `jit-tap-low-w80` | pass, pass, pass | pass, pass, pass | pass |
| jump-always-full | `jit-tap-low-l40` | pass, pass, pass | pass, pass, pass | pass |
| jump-always-full | `jit-double-higher-w40` | pass, pass, pass | pass, pass, pass | pass |
| jump-always-full | `jit-hold-higher-than-tap` | pass, pass, pass | pass, pass, pass | pass |
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
| no-shooting-in-air | `jit-c4` | pass, pass, pass | pass, pass, pass | pass |
| no-shooting-in-air | `jit-c5` | pass, pass, pass | pass, pass, pass | pass |
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
| camera-stops-right | `jit-r-far-e1` | pass, pass, pass | pass, pass, pass | pass |
| camera-stops-right | `jit-r-far-e2` | pass, pass, pass | pass, pass, pass | pass |
| camera-stops-right | `jit-r-far-e3` | pass, pass, pass | pass, pass, pass | pass |
| camera-stops-right | `jit-r-far-e6` | pass, pass, pass | pass, pass, pass | pass |
| camera-stops-right | `jit-r-far-e7` | pass, pass, pass | pass, pass, pass | pass |
| camera-stops-right | `jit-r-far-e8` | pass, pass, pass | pass, pass, pass | pass |
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

135 pass, 0 false-rejection, 2 indeterminate, 0 not-run.

## Trace digests from the fresh control runs

216 headless engine replays completed over 36 distinct routes. 36 routes produced identical trace digests on both arms. The engine ran in diagnostic mode with host filesystem, processes and network because the replay sandbox could not create a user namespace. The machine-readable report and raw traces were retained locally. The hashes below identify what was measured.

| Route | Canonical route SHA-256 | Clean trace SHA-256 | Comment-only trace SHA-256 |
| --- | --- | --- | --- |
| hold-left | `d0c42842b6ce4ddb5fd2ac8a72672ca4c72e2645519c037658c98696ee438dba` | `91f8e4d8449c629c3e114b62bf402c9c8268141236f7711834f938065b4c1edd` | `91f8e4d8449c629c3e114b62bf402c9c8268141236f7711834f938065b4c1edd` |
| hold-right | `9c1617e416ffef6b94643a19acd53d5596a014f46ba65910426bd1d4d93a87c6` | `7fb96d70951707c602bd59d3831938b7ff7a9665a93d65070ec8382a98f1f859` | `7fb96d70951707c602bd59d3831938b7ff7a9665a93d65070ec8382a98f1f859` |
| jit-air-shoot-1 | `f3f4175ced543380db5ac892a1ee22e14d00352f9fedf0e77da3a9bdb7aed076` | `0bee5704752f97d7976228bfd0d73db2986d8300779febaa7fe932250c256793` | `0bee5704752f97d7976228bfd0d73db2986d8300779febaa7fe932250c256793` |
| jit-air-shoot-2 | `a37c8d766e60e76fdbd771d5977e38898b7cbe005d5fba8369b98166ce825836` | `d426d5ec332affb4a2d8ca3fe908ae5d13cefe8e1c643ffdb64184f30d515b95` | `d426d5ec332affb4a2d8ca3fe908ae5d13cefe8e1c643ffdb64184f30d515b95` |
| jit-ground-shoot-1 | `7fb60c0b9f4179b017b18b73c11321ac6c828ced227656b4fd5cb23265d7b88b` | `14bf192e9b9ceae02da9ddbc9eef82cb8ffbb548f5aa66f81ceb1249cfa116a8` | `14bf192e9b9ceae02da9ddbc9eef82cb8ffbb548f5aa66f81ceb1249cfa116a8` |
| jit-long-hold | `e90be969c72d2c01bb0263817f3852bf56a96c1721e4a1b1d855c7bc9d8fa379` | `fac90daeff8ed456080348a745926447dc2b0790ccf5c8e26812ce55bd080b02` | `fac90daeff8ed456080348a745926447dc2b0790ccf5c8e26812ce55bd080b02` |
| jit-r-far-right-12s | `839d3e0e42c161373f26a2a55546c966a34a70ac22aa820cb67c830bb3db88d4` | `9e42bfcf63246b0aafd2b0d03589bf0f9342aa7b3eed822d3d117a2bc5d92a60` | `9e42bfcf63246b0aafd2b0d03589bf0f9342aa7b3eed822d3d117a2bc5d92a60` |
| jit-r-far-right-8s | `d095aa470ae5d1fc2bd1456ae82c6bfe26160579bdbbcb6d740e7e75c6219cb7` | `1f7c2f4f108bacc93f180946fceaa2d2a972063972a3c8a313da98c71307695d` | `1f7c2f4f108bacc93f180946fceaa2d2a972063972a3c8a313da98c71307695d` |
| jit-r-far-right-double | `e702dbfa1d9dd14c963c4bae74f23c1a960213a8d002b50e868359eff61da046` | `9353a11608d96b6b3b4b98f0da7e1e2c33ce1144038285c81330129abfc78890` | `9353a11608d96b6b3b4b98f0da7e1e2c33ce1144038285c81330129abfc78890` |
| jit-r-far-right-single | `4c7e8eaf9827a9a27a020fe8b781370b54f5eda018aba529bac3f9e7e1c2516d` | `09202c5a7764a25fe8e44312cad7aac24b4d8543db39b756a3e36143652e1af8` | `09202c5a7764a25fe8e44312cad7aac24b4d8543db39b756a3e36143652e1af8` |
| jit-r-jit-left38-dbl | `9abd632463304917b474c5474cf9779a66b24c30333dd55254fb2414de9242bf` | `25c117e581a7de7a319579f4f4e6eae62f2dc930b849e3c4ae1a428bf8acb48a` | `25c117e581a7de7a319579f4f4e6eae62f2dc930b849e3c4ae1a428bf8acb48a` |
| jit-r-jit-left42-dbl | `93b99f8603c54b6648f5c5bcfd0fe5a39c7d7b00ae0afbbcb07ec3bdd2e95be6` | `a796d588a3720904fbf5c3cd2100f258c3c7b9bc4d372a281b64a629e156941d` | `a796d588a3720904fbf5c3cd2100f258c3c7b9bc4d372a281b64a629e156941d` |
| jit-short-tap | `174bd0543af622478d6555d616b0846707f6e6bafd42b4c0941b34fa1097a382` | `29cb0b6ce8fce69b00393f782e3a8a79ce3bacf2ecdf97255c425f89c1aeb06c` | `29cb0b6ce8fce69b00393f782e3a8a79ce3bacf2ecdf97255c425f89c1aeb06c` |
| jump-l40-x1 | `23cc4bf727bccecb97c7210e1b507fcd6d7ab2af571170485b5af7321c63852f` | `1bb3de807a40a7340045ea35440b42408d7c4f027c1a8af599bf378c1e665908` | `1bb3de807a40a7340045ea35440b42408d7c4f027c1a8af599bf378c1e665908` |
| jump-l40-x2 | `ad66e9df192dfa2ae341196ce8c8634a6bc386e4ab1aec4e2cebf7bfd8d5743f` | `64875ac2109b26ca95b5265e4ec118a72fc844d9bdd6caab942e1bc7a2afcb73` | `64875ac2109b26ca95b5265e4ec118a72fc844d9bdd6caab942e1bc7a2afcb73` |
| jump-l40-x8 | `8808601f37e61321def50dfb3a0fdc566b8aa1996b73baad47457e12404ed857` | `687c8c8fc96a30779c8e22229e6e8271d758e16cfe01218566e52f090a0b36e7` | `687c8c8fc96a30779c8e22229e6e8271d758e16cfe01218566e52f090a0b36e7` |
| jump-w0-x1 | `05fbc284b8bda5425ab338a4ef235d9c07ccd95caeb2782fb017c5119a4596cf` | `70fd9e1a5e875755b6ac5b14eec4054f46f9f7559627c4db36381d25067eefb4` | `70fd9e1a5e875755b6ac5b14eec4054f46f9f7559627c4db36381d25067eefb4` |
| jump-w0-x2 | `b6cca17fb249a7685d9b7a1d01ed02e04251c0b1c343f96c145c5f6001bfe128` | `647df1a7d3bb9601f4a7cb5b5e4ec8aac71dc49d683193ddc6a1cba6a5ae0fb8` | `647df1a7d3bb9601f4a7cb5b5e4ec8aac71dc49d683193ddc6a1cba6a5ae0fb8` |
| jump-w0-x8 | `209cf72abe2851ee92b765d6cbb4fcda1bc032bebd259b7aa5de64e5e3500293` | `b1dc58e7419c54b90667198351944dfcbd0100b70bf5ebde79ffe96ba07358d4` | `b1dc58e7419c54b90667198351944dfcbd0100b70bf5ebde79ffe96ba07358d4` |
| jump-w120-x1 | `5e5434d594ddd3715569bc6381489a08c7a382599a98f56b045b8a626998b13f` | `83142b664d584099c50fceb9fd0583c989b1f2201983e9e10dc4178f329e6b43` | `83142b664d584099c50fceb9fd0583c989b1f2201983e9e10dc4178f329e6b43` |
| jump-w120-x2 | `ca4d763028dcf7ef8d83a47cfef24a0fae3ef5db138e215b070156bae5c5849a` | `914fd52bb009097c6f7f1a39d1afdc3bcfefaeed2a5f17a15c6519d227b5e24f` | `914fd52bb009097c6f7f1a39d1afdc3bcfefaeed2a5f17a15c6519d227b5e24f` |
| jump-w120-x8 | `a227fc1afba206f0f9cedc3df7965af5d25059d29bdfb5d14a0bcd927ca13063` | `3848c4e2537815cfe85de0613103faf19e31a5c8eb6f932fe43ee52dc3a12c26` | `3848c4e2537815cfe85de0613103faf19e31a5c8eb6f932fe43ee52dc3a12c26` |
| jump-w40-x1 | `67f3bdeec4fc32f4f42bb8e19138917a0c5e84cc54c762fce78172e34341a325` | `55e0ac5a2dde5bb5d5d28c18347f1d31354cad85f6fa06308b9a1fe5ff93b9f4` | `55e0ac5a2dde5bb5d5d28c18347f1d31354cad85f6fa06308b9a1fe5ff93b9f4` |
| jump-w40-x2 | `742850d7ab0d04de56d1aa2e23ac9c56bb3b725f8ada293947ef4c4aa4b65d79` | `e64a25fc2dab6cfcbf8774d7c04360bd15b63f94f0b79580e4296e42265a2713` | `e64a25fc2dab6cfcbf8774d7c04360bd15b63f94f0b79580e4296e42265a2713` |
| jump-w40-x8 | `bb8ffadfe5b02a47813a5e3a1949e9a3421342a0f92ef63c3a26c6f118a72778` | `304537c08bb351fa42e179bcb8b3643409b136de03a6bbe600753a0650c4a161` | `304537c08bb351fa42e179bcb8b3643409b136de03a6bbe600753a0650c4a161` |
| jump-w80-x1 | `03727ff8e274f7ca53064faf0820a5853a6be5b88c62072f259a135268d5f8e9` | `cd8cb2f161e5903b51fed91f2d92c56da0a47cedcbe9b0d9c2e82dc8bd366d5c` | `cd8cb2f161e5903b51fed91f2d92c56da0a47cedcbe9b0d9c2e82dc8bd366d5c` |
| jump-w80-x2 | `36e5b2628fb9e3b554277bc9ff2e5a70d38f09428572a8a70f5c2c5a76bb7995` | `00e09f3bfc31ca48b74eb14812956313cdbead10e9268d5658d454741e64490d` | `00e09f3bfc31ca48b74eb14812956313cdbead10e9268d5658d454741e64490d` |
| jump-w80-x8 | `2a9eb2a3cd276d5c259f8ac3a36489647ea9dd6930dc5d39a243e21f79737d5a` | `068e23fcd02af06316d57c94349cafa728eceb000f3c5cc6773b8fef8079f0bd` | `068e23fcd02af06316d57c94349cafa728eceb000f3c5cc6773b8fef8079f0bd` |
| move-fire-left | `4181e355f218f08f9a46dade50e9f044aa3c6159d8c436206ea18696b23e0f03` | `1c570ab26bade2bf203494fea66c55f93ead20848ab3088d6ea9b1298d4d904d` | `1c570ab26bade2bf203494fea66c55f93ead20848ab3088d6ea9b1298d4d904d` |
| move-fire-right | `fadad3101620ee5b4bd6929af6d35e1ad44eccf2aa5246b938b10b761984b409` | `51a8566b6bcb546e0a306eac079c8f513988bd09c45000cf1eda238fa7783a40` | `51a8566b6bcb546e0a306eac079c8f513988bd09c45000cf1eda238fa7783a40` |
| reverse | `d449b338f6c7efcc184c1a9140941d7e77047f0e98271125127b191f1c29ef80` | `7d028c3568f4901d9a886dc39f9e10def60d065941ce295240a1260b15e45f1f` | `7d028c3568f4901d9a886dc39f9e10def60d065941ce295240a1260b15e45f1f` |
| shoot-left-every12 | `e0742f3a18c47208c93e0d0ce97ce163daf65b44faff41efe7f811d0de0df6fe` | `33b1317b2e42e8a61781258b646b3a5a6563c36c5f24c60749016ddb6e78dd40` | `33b1317b2e42e8a61781258b646b3a5a6563c36c5f24c60749016ddb6e78dd40` |
| shoot-left-every48 | `f657f374af462f695bf01fa6a9e77fbe5d2a9a5d932f395aed17e729025bd1cf` | `33b1317b2e42e8a61781258b646b3a5a6563c36c5f24c60749016ddb6e78dd40` | `33b1317b2e42e8a61781258b646b3a5a6563c36c5f24c60749016ddb6e78dd40` |
| shoot-right-every12 | `e774115a4ccb465aa723e31e0bd4711fab5f5ad0553f9c6633ffdf05cee85dae` | `8a92fff7b303c3b286f46933240c82f89393b8cc5fc6513591ef73f155200753` | `8a92fff7b303c3b286f46933240c82f89393b8cc5fc6513591ef73f155200753` |
| shoot-right-every48 | `a294d061444e538ee9b0eb58eb71995e96df89f223edb44a7440f45f12879034` | `8a92fff7b303c3b286f46933240c82f89393b8cc5fc6513591ef73f155200753` | `8a92fff7b303c3b286f46933240c82f89393b8cc5fc6513591ef73f155200753` |
| wait-long | `0746f1753d65ce9bcd3ae28a70802c951b87c8e10c9b213f3bff1f08d9be29cd` | `655b6bfc25202d934aa19d6b5647993fc81a7fd94258ff1f10de1cc86a5234d0` | `655b6bfc25202d934aa19d6b5647993fc81a7fd94258ff1f10de1cc86a5234d0` |
