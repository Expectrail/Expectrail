# Offline observer calibration (#330)

This is an opt-in offline loop for the bundled game's **player**, tested on base
`5d25639b7e53e5989cf2eb062544727eeefb02e1`. It proposes from binding/asset names and already-recorded
phrases, selects on clean frames, proves on separate clean/broken frames, and writes a checked record.
It constructs no live client. Model noun-phrase generation, all-object project calibration, and
patch generation for arbitrary games are not implemented here.

## Audit of the issue's Done when

The audit used [the body and all comments of #330](https://github.com/Expectrail/Expectrail/issues/330),
including Sean's November 14 decisions, and merged PRs [#448](https://github.com/Expectrail/Expectrail/pull/448),
[#459](https://github.com/Expectrail/Expectrail/pull/459), and [#470](https://github.com/Expectrail/Expectrail/pull/470).

| Case | Evidence on base main | Result of this change / remaining |
| --- | --- | --- |
| Recorded SAM loop chooses a player-only phrase and rejects the enemy-matching phrase | `docs/sam.md`, October probes: “blue robot” unique; “small robot character” also matches enemies. `docs/run-it/vision/clean.json`, run [43508479160](https://github.com/Expectrail/Expectrail/actions/runs/43508479160), retains exact blue-robot answers. No general selection loop or raw ambiguous-phrase recording found on main. | New loop selects blue robot on 13/13 exact recorded selection frames. The ambiguous candidate has 13/13 unanswered questions, **not** 13 negative detections. Its enemy ambiguity is proved only by the labelled stand-in unit test. Genuine paired SAM comparison remains missing. |
| Broken copies all caught; clean passes | `tests/test_anchored_observer.py`: `test_the_clean_game_passes_on_what_is_drawn`, `test_a_player_not_drawn_is_a_failure_never_a_pass`; these are stand-ins. No bundled four-copy calibration proof found. | Frozen no-model observer: separate clean proof 12/12 pass; hidden, behind-scenery, texture-blanked and shifted-off-body each fail 13/13 sampled frames. SAM has no answers for these proof images: all four named as unproved. |
| Calibration record validates | `contracts/vision-calibration.v1.schema.json`, `expectrail/anchored.py::check_calibration`; `tests/test_anchored_observer.py::test_the_example_is_a_usable_calibration` and `test_a_hand_edited_verdict_is_refused`. Outside recording at `tests/outside/recordings/kinematic-character/calibration.json`. | New observer-neutral contract, example, writer and semantic reader. Both published records validate; outcomes/floors are recomputed, selection/proof PNG overlap refused. Older anchored format remains unchanged. |
| Changed texture makes calibration stale; dependent verification needs-review | Existing anchored record identifies game/commit, but does not bind texture bytes or check texture staleness. Missing. | New `CalibratedObserver` checks named textures, observer/version and recording/bank identity before use. `test_stale_calibration_yields_needs_review_in_the_real_gate`: fresh accept → stale needs-review. Disabling the digest check makes that test red (stale accepts). Saved real pixel capture gives the same transition; see the labelled transport stand-in record below. |
| Live calibrated loop on bundled game and one outside project | Outside [43652198623](https://github.com/Expectrail/Expectrail/actions/runs/43652198623): anchored calibration found/size/stable 19/19, clean accept, broken reject, harmless accept, invisible reject (the latter indirect). Sources: issue comment, `docs/outside-projects.md`, committed outside recording. Exact-image replay limitation remains #515. No recorded live automatic bundled phrase-selection/four-copy loop found. | No new live run. Sean owns dispatch and the remaining budget. This PR is **Part of #330**. |

The point calibration's `expectrail/anchored.py::RULES` are unchanged: Sean's 90% thresholds,
25% tolerances, pixel floors, 3 px nudge and two separate point requests still apply. Phrase/art
selection below is a separate box-scoring loop, not a replacement for those point rules.

## What was measured

Every figure below is generated from the linked records, whose PNG/replay digests, boxes and raw
scores are retained. [Source manifest](calibration-330/source.json) pins the engine, game tree,
patch bytes, sensor files, bank and recorded SAM source. Native PNGs, traces, plans and command logs
are in the handover evidence archive.

Before capture, `pre-capture-plan.json` fixed smoke as selection, the new
[proof route](calibration-330/proof-route.json), the four patches, and every-tenth-plus-last sampling.
The previously frozen #262 bank came from separate calibration routes; all its ten sensor/contract
source hashes matched this base. No bank or sensor threshold was changed on these frames. One clean
proof PNG identical to a selection PNG was excluded by digest before matching; this is recorded,
not counted as another independent observation. Only the sampled frames are claimed. All four broken-copy traces are byte-identical to the clean proof trace; the changed pixels supply the negative evidence.

| Observer / provenance | Selection | Separate clean proof | Hidden | Behind scenery | Texture blanked | Shifted off body |
| --- | --- | --- | --- | --- | --- | --- |
| [Frozen #262 pixel sensor](calibration-330/template.json), real engine captures, no model | 13/13 pass; player-art candidate; learned loop floor 0.949981 | 12/12 pass; 0/12 false alarms | 13/13 fail | 13/13 fail | 13/13 fail | 13/13 fail |
| [Genuine recorded SAM](calibration-330/sam-recorded.json), run 43508479160 | Blue robot 13/13 pass; floor 0.774176. Ambiguous phrase: 13/13 unavailable | 12/12 unavailable | 13/13 unavailable | 13/13 unavailable | 13/13 unavailable | 13/13 unavailable |
| Scripted stand-in, `LoopTest.test_unique_player_wins_and_the_enemy_phrase_is_rejected` | Blue robot selected; extra enemy box rejects ambiguous phrase | 8/8 pass | 8/8 fail | 8/8 fail | 8/8 fail | 8/8 fail |

The template bank's internal floor stays 0.9; the common loop learns its separate floor from
selection scores (lowest correct score minus 0.05, bounded by that observer's minimum).
Proof never changes the phrase or floor. A pass requires one above-floor answer overlapping the
engine box at IoU ≥0.5, with no extra above-floor answer. At least eight frames are required for
each phase/copy. Gaps do not count as absence or as catching a broken copy. Every missed or
unanswered copy is listed by name and disables that calibration.

The pixel sensor searches a region supplied by the engine and compares frozen art. It establishes
neither global semantic uniqueness nor transfer to other art. This small clean sample establishes
no general false-alarm rate or readiness for a release verdict; the existing #262 measurements and
opt-in status remain in force. Hidden/blanked/layered/shifted player defects were caught in this
local sample; the genuine SAM proof misses **all four by missing evidence**, not by measured false
negatives. The old ambiguous probe artifact lookup returned no artifacts (run 40653267793); its
surviving job 122698142572 log gives only aggregate match counts. Those were not turned into invented
boxes or PNG hashes.

## Reproduce offline

From the repository root, emit patches into a new external folder:

```sh
python3 -m agents.calibration_copies --game game/platformer --out /tmp/330-patches
```

Use `harness.run.run(..., patches=[patch])` on its normal copied game for each variant; the original
scene/art is never edited. `agents.calibration_copies` refuses to write inside the game. The handover
includes the exact captured patch files (the behind-scenery patch is the existing `bugs/layering/v1.patch`;
the generator's equivalent context has different patch bytes, with the same scene edit).

With `EVIDENCE` set to the unpacked handover's evidence folder, run the same loop on its saved captures:

```sh
python3 -m agents.calibrate_observer --observer template --bank "$EVIDENCE/bank.json" \
  --selection "$EVIDENCE/captures/selection" --clean "$EVIDENCE/captures/clean" \
  --broken "hidden=$EVIDENCE/captures/hidden=$EVIDENCE/patches/hidden.patch" \
  --broken "behind-scenery=$EVIDENCE/captures/behind-scenery=$EVIDENCE/patches/behind-scenery.patch" \
  --broken "texture-blanked=$EVIDENCE/captures/texture-blanked=$EVIDENCE/patches/texture-blanked.patch" \
  --broken "shifted-off-body=$EVIDENCE/captures/shifted-off-body=$EVIDENCE/patches/shifted-off-body.patch" \
  --game game/platformer --texture player/robot.webp --out /tmp/330-template.json
```

For the genuine SAM replay, replace `--observer template --bank ...` with
`--observer recorded-sam --recording docs/run-it/vision/clean.json --candidate 'blue robot'
--candidate 'small robot character'`. Exact PNG/question misses stay unavailable. The command reports
a disabled calibration as a measurement, not a process error. It never falls back to a live client. Recorded verification reuses the existing `RecordedObserver`, which disables the general SAM cache and exposes the exact recording identity to the guard.

`expectrail.calibration.read` checks the new record; `CalibratedObserver(inner, record, game)` is the
explicit adapter for a gate caller that depends on it. It refuses stand-in records, checks texture
and observer-source digests on `describe`, `look`, and `segmenter`, and applies the selected floor to player
answers. It adds no default CLI observer or automatic project-record discovery.

[Saved-pixel stale-art proof](calibration-330/stale-pixel-gate.json) uses the actual frozen pixel record,
saved engine trace/PNGs, an unchanged existing approved check copied into a temporary folder, and a
labelled saved-replay transport stand-in. The local fresh record says accept; changing texture bytes
makes it needs-review with `calibration is stale: texture digest changed`. This is plumbing proof,
not a hosted run, a human approval, or SAM vision evidence.

Still needed: recover exact raw ambiguous-phrase answers and their frames, plus recorded answers for
independent clean and four broken proofs, or have Sean collect them. The current recording cannot
answer new pictures. A live automatic loop on the bundled game remains unshown. No spend or dispatch
was made here.
