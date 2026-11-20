# Inspect and calibrate a clean public Godot project (#260)

These are engine diagnostics. They measure the clean project's drawing geometry,
visibility flags and ground record, not pixels, model accuracy or a candidate fix.
They never write an approval or change a tolerance. Use only a public project and
public routes; these commands do not locate private inputs.

1. Run `expectrail init --project PATH --adapter godot --dry-run`. This reads saved
   text scenes and prints the draft config and input route without running project
   scripts or writing files. It lists duplicate candidates instead of guessing.
   `expectrail inspect --project PATH --json` preserves the same static inspection.
2. Review the proposed player path, texture, actions and viewport. `expectrail init
   --project PATH` writes the metadata and draft route. For unresolved bindings it
   writes a separate review draft and says which setting to complete. This does
   not make a check or config approved. Physics rates below 60 or not divisible by
   60 now get the highest capture rate at most 60 that divides their tick rate.
3. Run `expectrail inspect --project PATH --at-tick 1`. This runs the pinned local
   engine headless and prints each bound object's full node path, measured world and
   screen box, engine visibility flag and viewport intersection. `--json` prints the
   `expectrail.inspection/v1` record. That command is #604's, on main
   (`expectrail.inspection`); this page documents `calibrate`, which is new here.
   `inspect --at-tick` writes no evidence folder: it bounds the tick by the route it
   replays, not by a fixed limit.
4. Run `expectrail calibrate --project PATH --route PUBLIC_ROUTE --godot ENGINE
   --out MEASUREMENT`. Relative route paths start inside PATH. This runs the same
   route three times, with seed and inputs preserved, without capturing images.
   It prints sizes, visibility, ground gaps on/off the floor, coins, unjudgeable
   counts and exact whole-trace stability. Add `--json` for every measured frame
   and its actual physics tick. It never downloads an engine. If ENGINE is omitted
   it looks for the local pinned engine/cache or a matching executable on PATH.
5. Read the measurements before choosing tolerances. A positive bottom-minus-ground
   gap means the box extends below the line. A clean player standing on a platform
   can be above the ground tilemap: the existing 5 px grouping reports those rows
   separately. Missing/ambiguous player, missing ground or unknown floor state are
   unjudgeable with frame/tick reasons, not silently airborne. No constants change.
   Replay differences give exit 5 and name what to investigate; they do not tune
   the project. Without `--out`, scratch evidence is removed after success; replay
   failures retain bounded logs outside the project and print their location.
6. Continue through the normal `expectrail verify` flow with the reviewed config,
   chosen routes and checks. Engine calibration alone cannot authorize acceptance.
   Only a person reviews a draft and approves checks through the existing process;
   a full verdict also needs its visual evidence.

`--at-tick` is an idle replay tick, not a tick on a supplied movement route. The
calibration route supplies that movement. Both commands run project scripts in the
normal harness copy: they do not edit the source project or run an editor.

`expectrail.setup-report/v1` is `calibrate`'s record and has no `mode` field:
`inspect --at-tick` has exactly one implementation, `expectrail.inspection` (#604),
and never writes a setup report.

## Recorded check on main 21fde1b4be9362d209852e3d44221d059d110643

The second project is `tests/projects/config-lane` from #259: `Actors/Avatar`, a
lookalike sprite, a moving camera, a 360×240 viewport and a 60 Hz tick. The bundled
game uses the proposed `Level/Player` binding, 800×480 and 120 Hz ticks/60 Hz capture.
The clean routes were `harness/routes/smoke.json` and `tests/projects/config-lane/walk.json`.
No game source, observation reader or verifier changed. Each project produced three
byte-identical complete traces. Source file hashes before/after setup were equal.

| Measurement | Bundled game | config-lane |
| --- | --- | --- |
| Engine frame samples; visible-player flag | 120; 120/120 | 120; 120/120 |
| Player width/height, min/median/max (px) | 64/64/64; 64/64/64 | 24/24/24; 24/24/24 |
| Ground available; unjudgeable | 120/120; 0/120 | 120/120; 0/120 |
| On-floor bottom minus ground, min/median/max (px) | -31.353/4.747/4.750 (n=66) | -0.075/-0.075/-0.075 (n=120) |
| On-floor rows >5 px above the ground tilemap | 29/66 | 0/120 |
| Airborne gap, min/median/max (px) | -85.605/-60.880/1.874 (n=54) | no airborne rows (n=0) |
| Recorded coin entries per frame (coin role not bound) | 0/0/0 (n=120) | 0/0/0 (n=120) |
| Whole traces identical | 3/3 | 3/3 |

Both configurations bind only the player. The zero coin-entry counts mean no
coin role was configured; they do not measure how many coins the games contain.
The ground line is measured separately by the harness.

These are engine samples at the configured frame cadence; no PNGs were captured.
The reports retain all frame samples and source config/route/tree/trace digests:
[bundled](onboarding-evidence-260/bundled.json),
[config-lane](onboarding-evidence-260/config-lane.json).
The [hand check](onboarding-evidence-260/hand-check.json) records arithmetic samples
and a separate comparison of every frame and statistic. The hand-check program
imports no observation or calibration helpers. It selects physics tick
`(frame+1)*(tickRate/captureFps)-1`, reads the measured screen box, independently
projects raw world coordinates with the next tick's camera, computes ground and
bottom-minus-ground, sorts values for the median, and totals the counts. Projecting
already-rounded world boxes agrees within 0.0011 px on the bundled run and within
0.0001 px on config-lane; the report uses recorded screen boxes before that second
rounding, and all reported measurements/statistics match exactly.

For example, bundled frame 0 is tick 1: world box `[58,590.75,122,654.75]`, camera
translation `[310,-260]`, screen box `[368,330.75,432,394.75]`. World ground 650 becomes
390, so the gap is `394.75-390=4.75`, width `432-368=64`, height `394.75-330.75=64`.
For config-lane frame 0, the moving camera gives box `[168,108,192,132]` and ground
`128+4.075=132.075`: width and height 24, gap `132-132.075=-0.075`.

The [real verify jobs](onboarding-evidence-260/verification.json) used the dry-run
config in temporary project copies, the named public routes, and a byte-for-byte
copy of the existing `player-stays-above-ground` check. Both engine results were
`pass`; both jobs completed `needs-review` (exit 2). These are not accepts: the
configs remain drafts, the existing check was approved before content binding,
and no visual observer ran. No approval was created or modified. The generated
first-input route was validated separately; the verify/hand-check runs explicitly
used the two named public routes, not a claim about coverage of the generated route.

## Contract, regressions and remaining work

`expectrail.setup-report/v1` has a closed schema, a real config-lane example, a
writer and a semantic reader in this patch. The reader recomputes statistics and
unjudgeable rows from all frame measurements, checks tick/frame coverage, and
refuses contradictory stability or digests. The schema and reader use no numpy,
PIL or JSON Schema dependency. The default Unity calibration result stays unchanged;
only the new explicit-measurements mode uses three decimal places.

`tests.test_setup_calibration` covers hand arithmetic, missing and ambiguous
measurements, invalid reports, setup corrections, replay instability, a no-extras
import, and real config-lane runs. Existing static init/inspect tests are unchanged.
Errors identify `--project`, the bound node/field, route/action, capture/tick rate,
local pinned engine, output directory or retained replay log to correct.

Part of #260. The literal issue's description of `init` opening a project headless
is not implemented: init deliberately remains static and read-only in dry-run;
runtime validation is explicit through inspect/calibrate and verify. Acceptance of
both proposed projects was not demonstrated. A person must review the drafts and
approve current check contents, and a separately authorized visual run is required
for acceptance. No new visual calibration loop (#330), live model, dispatch or
candidate-based tuning was run.
