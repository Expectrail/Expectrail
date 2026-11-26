# Read measurements and step through findings with the keyboard (#264)

## What changed

The evidence viewer keeps focus on the selected frame control after redrawing. The timeline shows the selected frame's reading for each side and observer, including frames without a saved picture. The jump button and current-frame announcement identify a first failure only when the After outcome records a failed check.

The interactive and static renderers select the earlier of the finding frame and the first engine difference. The numeric comparison continues to refer to the difference frame even when the opening pictures come from the finding.

The header names the policy and counts the public checks for which each observer returned a verdict on each side. Replay scope reports an explicit zero separately from an unknown count. The untested section also gives the compared and sampled frame-pair counts and recorded reason for incomplete visual position comparisons on public routes. A local Before tree can be identified even when there is no commit ID.

When repeated replays of the same public check and build include both a pass and a failure, both exports now show the ordered results on each side. The viewer gives a matching generic needs-review result a specific heading. Other decisions keep their own headings.

For an exact integer in an engine Label the viewer shows the expected score, terminal tick and original engine verdict reason. It checks the spec and observation digests before showing the reason. The check has no per-frame sprite readings. Both static rendering modes now display engine notes.

## What was run

The JavaScript from the renderer and the assertions from `tests/viewer_keyboard.cjs` ran in V8 with adapters for Node's assertions, VM and stdin. The regressions first failed on focus loss, absent frame readings and a missing finding-frame button. The combined candidate passed the stand-in assertions and the saved clean and fall-through samples.

The clean sample displayed 0 px at frame 0. The failing sample displayed approximately −0.004 px Before and 101.876 px After at frame 12. Both frames had measurements without screenshots. The fixture checks also covered a numeric zero, a missing point, an absent observation, an inapplicable check and a missing object.

The earlier-finding fixture failed on its opening frame before the change and passed afterwards in the JavaScript stand-in. With the saved stuck-fade view, opening moved from frame 20 with zero image elements to frame 0 with two. D selected the engine difference at frame 20 and F returned to frame 0. The saved restored repair opened at frame 20 with two image elements in both versions. Image decoding was not exercised.

The header, replay-scope and Base-row Python formatting functions ran in the Skulpt interpreter with the published clean and fall-through records. On fall-through the engine and vision each judged the one Before check. Only the engine judged the one After check. On clean there were no applicable Before checks, and both observers judged the one After check. Fixtures distinguished a review verdict from a missing answer and a replay error. A zero-replay fixture and the local Before tree reproduced the two previous misleading descriptions. The isolated checks passed after the changes. This verification used the production functions and a stand-in for the unrelated repair description.

The saved fall-through position check compared 0 of 13 sampled frame pairs. The previous scope section omitted this limitation. The candidate also passed isolated Python checks for partial and complete comparisons, zero samples, a stopped comparison and an absent position record.

The static measurements function also ran in both its folder and single-file modes on a constructed earlier-finding fixture in Skulpt. It returned two image elements at frame 0 and kept the numeric comparison at frame 20 (2 px Before and 7 px After). The harness supplied text escaping and exact-match regex adapters. This exercised HTML generation without decoding images or writing an export.

For the repeated-run change, the existing heading failed the new assertion in Skulpt. The candidate renderer showed the contradictory Before outcomes (fail, pass, pass) and three After passes in both export modes. Additional fixtures exercised a contradictory After, stable repairs, inconclusive outcomes, missing repeats, a job/record mismatch, and separate accepted, rejected and published decisions. The in-memory harness used the repository’s repair-block writer and state selection, with adapters for escaping and serialization. It exercised the renderer without writing files or starting the gate. The November 25 public repair and November 21 public bug records retained their published accept and reject headings without a disagreement table. For those two records the harness passed the public payload through the scrubbing boundary unchanged. A normal gate test using FlakyBase is included for native discovery.

The public four-tick score fixture reproduced four missing-sprite points on a pass and a withheld reading on both mismatches. After the change, Skulpt ran the evaluator, coverage and timeline functions and the viewer’s check, view builder and static measurement renderer on the fixture. The Label read 5, 10 and 0 against an expected 5 at tick 3. Both rendering modes displayed those engine readings. Zero pickups and a missing observation retained needs-review, and mismatched input digests withheld the reason. The standalone harness used a SHA-256 and canonical-JSON adapter, equivalent container operations, and text escaping. It exercised HTML generation without file I/O, a native interpreter, browser or game replay.

## Not done

This patch reconstructs the documented viewer behaviours. Byte identity with the original queued branch has not been established. The historical baseline was fetched. All 57 focused viewer tests passed, including the Node keyboard tests. Full Linux discovery ran 6,119 tests with 57 skips. The export scan checked 1,400 files with zero errors or warnings. Headless Chromium timed out opening the generated local exports, so browser verification remains pending. The participant trial remains with Sean or Timothy.

## Files

- `expectrail/viewer.py`
- `tests/viewer_keyboard.cjs`
- `tests/test_viewer_measurements.py`
- `docs/new-work/2026-11-26-viewer-frame-controls.md`
