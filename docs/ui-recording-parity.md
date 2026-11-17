# UI recording: default trace byte parity (#285, PR #573 rework)

Main reference: `ec0919b60c03abf033ef79a996880300658e6887`. Rework starts at PR branch head `021bbbc1a388fa0947d81d188d0861671541bba1`.

No trace spec requests UI data in these comparisons. **16/16 pairs are byte-identical; all 32 traces omit `uiIntegers`.**
Both files of each pair were compared as raw bytes, without deleting fields or normalizing JSON.

Godot `4.7.2.stable.official.ed1daf0bf`; rendered captures use OpenGL3 / Mesa llvmpipe (LLVM 19.1.7).
Each case is run under both headless and rendered capture. These are public diagnostic replays with
sandbox off, no model, no vision evidence and no new reproduction-rate or isolation claim.

Sources: the bundled game and `bugs/physics-fall-through/v1.patch`; kinematic-character and Dodge the Creeps
at `b761b4cd5718a7118f2c95eb55f181d0a5f004f1`; Breakout at `0ac7aed444ea593a023d9b666c211d7ab8acd51e`.
The existing public routes and seeded patches are used unchanged. Breakout remains on its existing
menu-only keyboard route: its broken copy is a serialization comparison, not bug-detection evidence.

The rework handover contains `evidence/parity/comparison.json`, both raw trace files for every row,
frozen main harness sources, original replay metadata, source digests and the reproduction script.
The branch lacked main's integer viewport serialization; its one-line change is carried over so
Breakout writes `[360,640]`, rather than silently treating `[360.0,640.0]` as byte-equivalent.

| Mode | Case | Rows | Bytes on each side | Matching SHA-256 |
| --- | --- | ---: | ---: | --- |
| headless | `bundled-pinned` | 360 | 276466 | `b768743689615da4d343ae05706befcd361548e57b7d3e5b14a36b500e8d20f3` |
| headless | `bundled-fall-through` | 360 | 268802 | `28420832be781cb864554e46197c7098a4c5cbc36f3232c6138f073aa6f3159a` |
| headless | `kinematic-character-pinned` | 360 | 117337 | `c9ac9129e578ae6c8f5e4a2ed2f5445f1cb5ce59428e642bb79f5daf3481c253` |
| headless | `kinematic-character-broken` | 360 | 110062 | `cadda54065100ae093a4dd7b47a7657772e0f06cf90addace2309920d9e23c4d` |
| headless | `dodge-the-creeps-pinned` | 300 | 59460 | `a6607dcef8095684c43ea9595fc26ade2fcf4ddb297f5bdce8ab832956903e66` |
| headless | `dodge-the-creeps-broken` | 300 | 62282 | `02e4d221a789f255a61d9bbb713b670b602f3a356a6b62dc769b06bb633877b1` |
| headless | `breakout-pinned` | 120 | 61568 | `e35b764dda4576eedf547883b4194e80ee6245b56ee729f60a639be01e693bda` |
| headless | `breakout-broken` | 120 | 61568 | `e35b764dda4576eedf547883b4194e80ee6245b56ee729f60a639be01e693bda` |
| rendered | `bundled-pinned` | 360 | 321532 | `2b8b5538594c55c455e2fbbf43a1c46dcc7ca6d6289359f0b0d7a54cc4c0e8ed` |
| rendered | `bundled-fall-through` | 360 | 313574 | `60931c815505981607533fed0766c8c3eeca5e35d1e01ddc62d39232234d9fd9` |
| rendered | `kinematic-character-pinned` | 360 | 130629 | `d3e80ebba2515c39bfa22251ece8135707ace842c3002daa8ef8ad50173deb05` |
| rendered | `kinematic-character-broken` | 360 | 123354 | `93d462b0a3469ac5dbda8e1942e7c9e8f3fb61170c08d4636f226d8309dcef6a` |
| rendered | `dodge-the-creeps-pinned` | 300 | 57850 | `7f7783d69988b3d6d05c6f7d18cce43a211af31a2c52e735003954588b11f9e0` |
| rendered | `dodge-the-creeps-broken` | 300 | 60672 | `166a891fac61e08fcb275d59b397253252d027c0ddb3db794094b5460b4e1412` |
| rendered | `breakout-pinned` | 120 | 61698 | `0e93258138fe758b42826ca419aff4f339880862aa15c303a10af5cb1109366e` |
| rendered | `breakout-broken` | 120 | 61698 | `0e93258138fe758b42826ca419aff4f339880862aa15c303a10af5cb1109366e` |
