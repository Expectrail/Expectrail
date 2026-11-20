# Offline counting audit of the public reproduction bench (#271)

Existing recorded model outputs only; no model call or replay. No trusted source certificate/context is supplied.
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

Of these, 91 are recorded as valid by the legacy keep rule; 46 are dropped proposals retained only as advisory diagnostics. No outcomes were replayed.
