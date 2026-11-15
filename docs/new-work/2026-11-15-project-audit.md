# Audit the outside trial, project config and onboarding (#263, #259, #260)

## What changed

Audited main `522ac07f25a71d1dcf58efc71b46260bf86d991e` against the issue bodies and their
scope decisions. None of these issues has all its evidence yet. This change fixes small setup
failures and records the missing work, rather than treating merged slices as completion.

- A config path that is a directory or link no longer falls back to the no-config path. It names
  the file to restore. A genuinely absent config retains the legacy behaviour.
- Godot's short, recursive node lookup requires one exact name; it no longer selects the first
  match or uses wildcard matching. An explicit node path still selects that path. A player binding
  to a non-spatial `Node` refuses with its name and the required `Node2D` type.
- Static inspection reports missing scene-header fields, duplicate resource IDs and unresolved
  scene instances with the scene name and a fix, instead of a bare key error or last-wins lookup.
- A self-written `config-lane` fixture has `Actors/Avatar`, two sprites using identical art, a
  moving camera and a 360 × 240 viewport. Its config is a draft; no check was approved.
- The outside vision judge now uses the same trusted per-project spec selection as the no-key
  trial. It previously always copied the bundled ground check, even for Dodge. Invalid selections
  refuse before calibration. Two stand-in capture tests fail on the old code and pass with the fix.
- The outside-project page now reports the latest #473 trial, Sean's existing Dodge approval and
  the distinction between historical engine-only accepts and the current requirement for vision.

### #263 — outside-project trial

| Case from Build / Done when | Evidence on main, or missing |
| --- | --- |
| Two distinct public Godot 2D projects, licence, full pin, why chosen; pinned fetch rather than vendored game | `tests/outside/projects.json`, `docs/outside-projects.md`; `tests.test_outside_trial.ListTest.test_every_project_is_pinned_to_a_full_commit_and_has_routes_of_ours`. Platformer and top-down, both MIT, pin `b761b4cd5718a7118f2c95eb55f181d0a5f004f1`. Both are from the same demo organisation; the doc's outside-organisation replacement before counting them for release is still missing. |
| Init, route, calibration, two or three person-approved checks **for each** project | Partial. `tests/check_onboarding_games.py` and the [inspection work log](2026-11-14-draft-project-inspection.md) record static init/inspect on both. Routes are checked in. Kinematic has a used clean calibration and one reused ground check; Dodge has one Sean-approved bounds check. **Fixed here:** the vision judge now respects that selection (`SelectedVisionPolicyTest`), instead of always using the bundled ground check. **Missing:** complete flow, Dodge visual calibration, and two or three checks per project. |
| Clean, seeded bug and harmless change with run links | [Run 43748180876](https://github.com/Expectrail/Expectrail/actions/runs/43748180876), #473 head `5cd3bc7b29aa3a50f8a8a9403cbdc5ff07e4193e`, `outside-trial` job success. Both pinned and harmless are needs-review without vision; both broken reject. Kinematic first violation frame 44; Dodge frame 97. [First vision run 43652198623](https://github.com/Expectrail/Expectrail/actions/runs/43652198623) separately accepted pinned/tinted kinematic and rejected broken/invisible. No Dodge vision accept is evidenced. |
| Per-project setup steps, machine and human time, what was/wasn't measurable | `docs/outside-projects.md` now distinguishes machine verification times and static setup command times from **missing human minutes**. Platformer: ground crossing; Dodge: in-play origin bounds, not enemy behaviour, scoring or drawn art. **Missing:** one timed end-to-end setup session per project with every stop recorded. |
| Obstacles become issues; core adaptation is recorded as trial failure | #338 input delivery, #346 missing ground, #348 edge columns, #388 platform bodies, #398 deep ground, #385 patch application, #330 visual calibration, #473 Dodge origin/box/lifecycle. These needed core changes: the original no-core-edits trial failed that criterion. The current runs do not retrospectively prove the original configuration-only claim. **Missing:** a fresh complete config/hooks-only onboarding trial and its obstacle log; runtime inspection/config gaps below remain blockers. |

Current #473 source: the [outside-trial artifact](https://github.com/Expectrail/Expectrail/actions/runs/43748180876/artifacts/14175650515),
`outside-trial.md`, `outside-trial.json` and each job's `findings.json`. The handover preserves this
public artifact and its API metadata. A successful job by itself is not evidence of an accept.

### #259 — project config and Godot bindings

| Case from Build / Done when | Evidence on main, or missing |
| --- | --- |
| Schema, example, reader; reject unknown fields, out-of-root paths, ambiguous selectors; texture/provider references | `contracts/project.v1.schema.json`, `contracts/examples/project.json`; `tests.test_project_config.SchemaTest.test_unknown_fields_sizes_and_ambiguous_bindings_are_refused`, `ReaderTest.test_a_present_config_that_is_wrong_names_the_field`, `SandboxValuesTest.test_the_sandbox_is_given_values_and_not_the_config_path`. Version/toolchain/entry/viewport fields are validated metadata; `harness/run.py` passes bindings and capture rate, not overrides for all these settings. **Missing evidence:** that a declared scene/viewport/physics/toolchain mismatch is enforced or refused, rather than merely retained as metadata. |
| Every bound object's screen box, visibility and role per tick, observations from boxes | Partial: player's `body`, `view`, `playerVisible`; enemy/projectile world boxes in `tests.test_object_boxes.BundledGameTest` and camera conversion in `ReaderTest.test_the_camera_scales_and_moves_the_box`. **Missing:** generic per-role screen boxes and visibility for every configured object, including coins/arbitrary roles. Godot does not emit Unity's `objects` records. Coins and ground feet still use constants in `agents/observations.py`; those constants are not confined to the bundled path. |
| Second test project with different names, similar sprites, moving camera, other viewport verifies through config alone | Partial on main: `tests.test_second_project.RealGodotTest.test_the_second_project_passes_the_engine_and_the_evidence_names_its_tree` covers crate-run (conventional `Player` name); `tests.test_app_projects.ConfiguredAppTest.test_second_project_lists_its_configured_policy_and_app_cli_have_same_inputs_and_accept` proves CLI/app wiring with stand-in replay and vision. **Added here:** `tests.test_project_audit.RealBindingTest.test_full_node_path_and_unique_group_track_the_same_moving_body_and_camera` replays the distinct fixture in real Godot using only its config; both selectors yield identical 120-row traces. **Still missing:** a complete real CLI verdict on this full-shape fixture from reviewed init output, with approved checks and matching visual evidence. A replay/trace assertion is not that verdict. |
| Missing or ambiguous bindings are named setup errors, never passes | Main covered a missing player and a non-unique player group. **Fixed here:** ambiguous short node names and non-spatial player nodes, with real red/green tests in `RealBindingTest`; `ConfigPresenceTest` covers directory/broken-link config paths. **Missing:** equivalent checks for every arbitrary bound role, alongside generic role recording above. |
| Bundled config reproduces decisions and hashes exactly | **Missing:** bundled config and config-versus-legacy parity. `tests.test_project_config.ReaderTest.test_the_crate_loads_and_the_bundled_game_has_no_config` explicitly requires no bundled config today. The [config integration log](2026-11-14-project-config.md) records unchanged seeded/sample decisions. This patch's real headless bundled smoke trace is byte-identical before/after; that does not prove frame hashes or config-versus-legacy equivalence. No bundled game file or existing assertion was changed. |

### #260 — init, inspect and calibration

| Case from Build / Done when | Evidence on main, or missing |
| --- | --- |
| Init discovers scenes/nodes/actions/rates/viewport; dry-run read-only; duplicate candidates never guessed | Static saved-text-scene implementation: `tests.test_init_inspect.SetupTest.test_inspect_and_dry_run_are_read_only_and_match_the_written_drafts`, `test_two_players_are_listed_and_neither_is_bound`, `test_animated_player_keeps_all_texture_choices_and_writes_review_files`. **Missing:** the originally requested headless/runtime discovery; authored scenes cannot reveal dynamically spawned objects. |
| Inspect runs to `--at-tick N` and emits bound node paths, screen boxes and visibility as JSON | **Missing.** Current `inspect --json` describes authored scenes only; there is no `--at-tick` option or runtime measurement. It needs the generic binding/box work above, a replay boundary and a contract, not a second static parser. |
| Calibration on clean build, hand-checked sizes/ground/visibility and three replay stability | [Scope decision on #260](https://github.com/Expectrail/Expectrail/issues/260#issuecomment-6817828493) assigns calibration to #330 and says not to build a second calibration here. `tests.test_anchored_observer.CalibrationTest.test_a_model_that_sees_the_player_is_enabled`, `test_a_model_that_answers_with_the_tiles_is_not_enabled`, and `test_the_example_is_a_usable_calibration` cover the existing visual calibration rules; checked-in kinematic calibration and run 43652198623 supply real evidence. **Not evidence of the original table:** no public `expectrail calibrate` command or hand-checked, three-replay ground-edge table for both bundled and second fixture. Track this remaining original requirement with #330, or have Sean explicitly revise it. |
| Bundled and second fixture init dry-run proposes config that then verifies | Proposal evidence: main's `SetupTest.test_inspect_and_dry_run_are_read_only_and_match_the_written_drafts`; new `SceneDiagnosticTest.test_dry_run_resolves_a_nonstandard_name_and_keeps_both_similar_sprites`. Drafts correctly cannot accept (`tests.test_ci_gate.VerifyTest.test_a_draft_config_from_init_is_never_the_ground_for_an_accept`). **Missing:** a reviewed, approved, complete real verification of the produced drafts on both fixtures; current real fixture test uses its checked-in draft config only for replay. |
| Every setup error names what to change | Existing texture/duplicate/output-link tests in `SetupTest`; new `SceneDiagnosticTest` red/green tests add absent/duplicate resource IDs, absent fields and unresolved instances with scene/reference/fix. **Not a claim that every possible Godot error is covered:** unsupported runtime discovery and generic bindings still need their own diagnostics/tests. |
| Public build only; read-only inspection, no private verifier inputs | `SetupTest.test_inspect_and_dry_run_are_read_only_and_match_the_written_drafts`, `test_output_directory_link_is_refused`; `expectrail.onboarding.resource` confines scene/image reads to the selected project. Current implementation never starts the game during inspection. |

## What was run

- Required historical fetch, then current main/claimed branch fetched; branch fast-forwarded from
  `9f9ff33751e9f34566d5fa2d2ffcf75080644bde` to base `522ac07f25a71d1dcf58efc71b46260bf86d991e`.
- Before suite: `python3 -m unittest discover -v -s tests -t .`: 3,987 tests, 454.395 seconds,
  zero failures/errors, 46 skips. Test runner wall time 456.998 seconds.
- Red, unchanged product: eight offline tests produced nine failures (four are subcases of one
  malformed-header test); four real Godot tests produced two failures. Logs are in the handover.
- Green: 24 offline focused tests pass; all four real Godot binding tests pass (35.741 seconds).
  Godot 4.7.2, headless, self-written fixture, sandbox off; no display, model or network needed.
- Bundled smoke route, before and after, headless with no image capture: identical trace SHA-256
  `3ae192deca6d1fae5fa6677da690058c8c0bcd6845653d379cf741900128c925`.
  Trace/log/measurement files are in the handover; no rendered-image parity is claimed.
- The first after-suite passed: 3,995 tests, 414.841 seconds, 47 skips, zero failures/errors.
  Audit then found the vision judge's wrong-spec selection. Its two new tests were red on that
  code (`red-selected-policy.log`) and green after the shared-selection fix. The final suite was
  rerun with that fix; the first log is retained as `after-first.log`.
- The next after-suite hit disk pressure: 3,997 tests, 443.946 seconds, 77 errors, one failure,
  47 skips (`after-disk-pressure.log`). Every error contains `Errno 28: No space left on device`.
  The failure was `tests.test_replay_sandbox.DiskBoundTest.test_a_folder_the_game_makes_unreadable_is_cannot_tell`:
  the watcher caught the file exceeding its limit before the child changed permissions. It passed
  unchanged on an isolated rerun (`sandbox-race-recheck.log`). Disposable package/import caches
  were removed, and completed synthetic fixtures were cleaned at earlier module boundaries to
  avoid their disk peak. No test or product assertion was changed. The failed attempt's full
  name comparison is preserved in `disk-pressure-comparison.json`.
- After suite: `python3 -m unittest discover -v -s tests -t .`: 3,997 tests, 390.880 seconds, zero failures/errors, 47 skips. Failure-name sets before and after are both empty. The only added skip is `setUpClass (tests.test_project_audit.RealBindingTest)`, named Godot 4.7.2 unavailable at the default lookup; all four tests passed separately using the retained engine's explicit path. No existing skip or skip reason changed. Logs and comparison are in the handover.

## Not done

Part of #263: full timed human/config-only onboarding, two or three person-approved checks per
project, Dodge vision evidence, and the documented outside-organisation replacement.

Part of #259: generic per-role box/visibility observations without non-bundled constants,
config-backed bundled parity, enforcement evidence for declared runtime settings, and the complete
real CLI verdict for the new full-shape fixture.

Part of #260: runtime discovery/`inspect --at-tick`, reviewed init-to-verdict evidence on both
fixtures, and the remaining original calibration evidence assigned to #330.

No approvals, models, paid calls, CI dispatches, GitHub writes, commits or pushes. No foreign game
was replayed locally: the outside evidence is the recorded CI artifact. No macOS or Windows run.

### Exact steps left for Sean

1. Keep the three issues open and label the approval/live-run items `needs-sean`. This audit does
   not approve checks or reinterpret Done when as complete.
2. For each pinned public project, run a new timed onboarding session using
   `docs/first-user-test.md`. Record human minutes separately from command seconds; start with
   `expectrail doctor`, then `expectrail inspect --project PATH --json` and
   `expectrail init --project PATH --adapter godot --dry-run`. PATH is that project's pinned
   checkout. Inspect has no `--at-tick` yet. Record the stop rather than inventing runtime output.
3. Review the proposed bindings, image and route; resolve Dodge's multiple image choices. A draft
   config must stay a draft until that review; after reviewing it, remove the `draft` field rather
   than setting it to false. Choose two or three meaningful checks per project,
   review clean/seeded/harmless evidence and personally approve each chosen file, using
   `python3 -m expectrail.spec_writer approve SPEC --by "Sean Keluo-Udeke"` only after that review.
   SPEC is the reviewed file. The existing Dodge approval is already valid; do not rewrite it.
4. The trial currently selects one spec per project. A follow-up builder must extend that selection
   for a multi-check trial, with tests, before the two/three-check run can be claimed. Use the
   existing sandboxed **Outside projects trial** workflow (`outside-trial.yml`, main, no inputs)
   to repeat the current single-check baseline; it cannot establish the missing multi-check flow.
5. For Dodge vision, first have the #330 owner resolve/calibrate its animated multi-image player
   and check applicability. Only then, if Sean chooses to spend, Actions → **Outside vision** →
   Run workflow → main → `project: dodge-the-creeps` → `sam_usd_cap: 2.00`. Sean alone approves
   the protected `main-only` job. This is a cap, not a promised cost or result. Read calibration,
   findings and spend artifacts; a refused calibration or cap stop is not a verified project.
6. To require the new real regression in CI without a new job, Sean can replace this existing line
   in `ci.yml`'s `capture-smoke` step “The position log carries the player's own box”:
   `run: python -m unittest tests.test_body_box -v`
   with `run: python -m unittest tests.test_body_box tests.test_project_audit.RealBindingTest -v`.
   Keep its existing `EXPECTRAIL_ENGINE_TESTS: required`. No workflow was changed here.

## Files

- `expectrail/project_config.py`
- `expectrail/onboarding.py`
- `harness/godot/expectrail_harness.gd`
- `tools/outside_vision.py`
- `tests/test_project_audit.py`
- `tests/projects/config-lane/` (project, scene, script, art, draft config, route, README)
- `docs/outside-projects.md`
- `docs/new-work/2026-11-15-project-audit.md`
