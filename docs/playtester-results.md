# Seeded playtesting and engine-only filtering (#531)

On November 15, 2026, four seeds (0–3), each 1,200 physics ticks from the start, were played on the clean bundled game and each public `bugs/reported/*.patch` applied to its own copy: **24 discovery replays, 5 producer reports**. Base commit: `e18dd3ef5267175166743c17a7b37480a292f3c0`. No original game file changed. This is development reproduction after reading the public reports, not blind discovery.

The engine was **Godot 4.6.3.stable.official.7d41c59c4**, Python 3.12, Linux, headless with no captured frames, through `harness.run.run(capture_frames=False)`. The repository pins 4.7.2; that version was not run. Bubblewrap was unavailable (UID-map probe failed); the harness recorded the isolation choice in every replay. No models, paid APIs or fixer calls were used.

The producer detects only below-level falling, sustained immobility during a movement hold, and repeated facing alternation during steady horizontal motion. Thresholds, commands and limitations are in [the playtester README](../tools/playtester/README.md). No generated check, approval or inferred cause appears in a report.

## Reports per build

| Build | Seeds | Reports | What the producer reported |
| --- | ---: | ---: | --- |
| `clean` | 4 | 0 | None |
| `air-jump` | 4 | 1 | Seed 2: character stops during a movement hold; **not** an infinite-jump finding |
| `body-flip` | 4 | 4 | Seeds 0–3: repeated turning during steady movement |
| `enemy-ledge` | 4 | 0 | None |
| `gun-cooldown` | 4 | 0 | None |
| `platform-z-order-pr927` | 4 | 0 | None; this patch reapplies an upstream draw-order fix, rather than adding a bug |

**Known symptoms found: body-flip, 4 of 4 seeds. Known symptoms missed: air-jump, gun-cooldown and enemy-ledge.** The immobility report from air-jump is an observation that repeated, not proof of the named bug or of a cause. It may describe an intended obstruction. Reproduction alone cannot establish that a report is a real bug.

“Not reported” must not be relabelled “never reached.” An audit of the recorded traces shows behavior differences for all four public known bugs; no known bug was wholly unreached across these four seeds:

| Known build | Recorded reach evidence, seeds 0 / 1 / 2 / 3 | Detection limit |
| --- | --- | --- |
| `air-jump` | Minimum player y: 151.277 / -207.009 / 146.977 / 74.294; clean: 513.207 / 392.644 / 276.325 / 435.314 | No detector for excessive jumping; the one stop report does not describe that symptom |
| `gun-cooldown` | Distinct recorded bullet IDs: 29 / 23 / 39 / 25; clean: 19 / 16 / 22 / 16 | No detector for firing cadence |
| `enemy-ledge` | Enemy 0 drops 276.85 px after its first 60 recorded samples in seeds 0, 1 and 3 (clean 20.85); seed 2 only 20.85 px | No detector for enemy falls; the large drop was never reached in seed 2 |
| `body-flip` | Alternation report at ticks 460 / 116 / 24 / 812 | This is the known symptom actually reported |

Enemy-drop audit means maximum y after sample 60 minus minimum y in samples 0–59, by trace ID; it is descriptive reach evidence, not an additional producer rule. The draw-order patch requires rendered evidence; these trace-only runs cannot establish whether its visual symptom was reached. `coverage.json` in the handover contains the measurements.

## Engine-only filter count

**Of 5 actual producer reports plus 2 hand-written false reports, 2 of 7 would be filtered: 1 not-reproduced, 1 anchor-desync.** Both deliberate false reports were filtered; all five producer observations repeated. There were 21 fresh filter replays (three per report), plus one source replay for the hand-written idle anchor: 46 successful engine replays in total including discovery. All seven groups of three full traces were identical. The five producer reports were regenerated identically from the independent filter traces.

Each report was replayed on **its own unchanged target build**: the applicable bug patch stays present, no candidate fix is applied. Reproduction asks whether the same producer observation first appears at the stated `faultTick`. Anchor reach is checked independently at `preFaultTick` within 2 world pixels. The wrong-anchor report copies the first real producer report (air-jump seed 2), with only its anchor x displaced by 10,000 px and manual identity. The idle false report claims falling at tick 100 on a clean 240-tick route with no inputs.

| Report ID | Build / seed | Anomaly reproduces | Anchor reached | Full traces identical | Engine-only filter result |
| --- | --- | ---: | ---: | --- | --- |
| `playtest-23202216ce59e3b63b9fab0c410d3514` | air-jump / 2 | 3/3 | 3/3 | yes | `reproduced` |
| `playtest-e0e5c9b86b2fc8f24a3de7e36285a463` | body-flip / 0 | 3/3 | 3/3 | yes | `reproduced` |
| `playtest-473da8ea573df344d27d04cd967f18cc` | body-flip / 1 | 3/3 | 3/3 | yes | `reproduced` |
| `playtest-a708fd9d6baa2a8c423e1d5e3c0c83f1` | body-flip / 2 | 3/3 | 3/3 | yes | `reproduced` |
| `playtest-c98cf164364e797768ae9be8f954340e` | body-flip / 3 | 3/3 | 3/3 | yes | `reproduced` |
| `false-idle-fall` | clean / 0 | 0/3 | 3/3 | yes | `not-reproduced` |
| `false-wrong-anchor` | air-jump / 2 | 3/3 | 0/3 | yes | `anchor-desync` |

This is **not** the ingest command or the shared verifier: it is a local bench measurement using the producer’s fixed observations. It does not interpret arbitrary bug prose, select/approve checks, produce accept/reject verdicts, or send anything to a fixer. `anchor-desync` takes precedence even though the wrong-anchor report’s symptom reproduced 3/3. Integrating these report documents with the shared reproduction path belongs to the other #531 builder.

## Recorded commands and evidence

```sh
python3 -m unittest discover -s tests -t .  # before changes, all EXPECTRAIL_* removed
python3 -m unittest tests.test_playtester -v
mkdir -p work/runtime/data work/runtime/cache work/runtime/config
XDG_DATA_HOME="$PWD/work/runtime/data" \
XDG_CACHE_HOME="$PWD/work/runtime/cache" \
XDG_CONFIG_HOME="$PWD/work/runtime/config" \
python3 -m tools.playtester.bench --out work/playtest-measurement \
  --seeds 4 --ticks 1200 --godot /usr/local/bin/godot
python3 -m unittest discover -s tests -t .  # after changes, all EXPECTRAIL_* removed
```

Full suites ran with all `EXPECTRAIL_*` variables removed: before, **4,028 tests in 444.353 s, 47 skipped, exit 0**; after, **4,041 tests in 568.126 s, 47 skipped, exit 0**. No failing unittest test names. The focused playtester run passed all 13 tests. Some fixture tests deliberately print failure/error messages; the actual suite summaries are both `OK`.

The first benchmark attempt without writable XDG directories aborted during its first clean replay: Godot could not create its user data under the read-only home and crashed. It produced no reports and is excluded from the 46 successful replay count; its error log is included in the handover. The successful experiment uses writable XDG directories without changing HOME.

The handover zip retains the before/after suite logs and exit codes, focused-test log, experiment log, all seven report documents (including the two manual reports), every successful replay’s raw trace/replay/engine log and route, build commits/patch hashes, coverage audit, and report-shape audit. Original report field sets were compared with the issue table, and embedded routes validated against the existing `contracts/route.schema.json`. No parallel report schema was created. The five patched target commits can be recreated using `tools.playtester.bench.build_commit(base, patch)`; the audit reconstructed them and compared every game blob to the replay input.

## Not run

No pinned Godot 4.7.2 run, rendered-image verification, ingest/shared-verifier integration, generated check, fixer or end-to-end repair-rate measurement. No held-out or blind content was used. The observations have no general guarantee of bug precision or coverage beyond the recorded seeds.
