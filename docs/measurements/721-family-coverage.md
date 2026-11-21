# Draft checks by verification family (#727)

Each row records what an individual draft can judge on a public route. The linked measurement
gives the coordinate frame, reproduction command and any additional controls. Drafts require
human approval before they can judge changes in the release gate.

| Family | Draft and scope | Clean | Public defect | Do-nothing | Harmless edit | Reproduce |
| --- | --- | --- | --- | --- | --- | --- |
| Movement and input | [`player-reaches-opening-coin`](../../specs/drafts/727/player-reaches-opening-coin.json). Direction and arrival only, not speed. Half speed reached the coin and passed 3/3. | 3/3 pass | Wrong direction, 3/3 fail | Frozen player, 3/3 decisive fail | Comment-only, 3/3 pass | [Opening walk measurement and command](727-opening-walk.md#reproduce) |
| Spawning and enemy behaviour | [`middle-enemy-on-return`](../../specs/drafts/727/enemy-patrol/checks/middle-enemy-on-return.json). Presence and location of the middle enemy during the return window. An enemy frozen inside the region passed 3/3. The missing upper enemy also passed 3/3. | 3/3 pass | Fast left, 3/3 decisive fail | Frozen at spawn, 3/3 decisive fail | Comment-only, 3/3 pass | [Middle enemy measurement and command](727-middle-enemy.md#reproduce) |
