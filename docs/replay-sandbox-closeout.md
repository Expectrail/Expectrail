# Replay sandbox close-out audit (#253)

Audited `d877ddb647161e4af28aa554e7886d91e1b83f5b` on November 16, 2026.
Read the issue body, all 14 prior comments plus the new claim, and linked PRs
#300, #304, #312, #313, #505 and #534. Checked open #574 before harness edits:
its head `2bbaecf25f3b02625dd68342a32189bf1f79718e` lists only
`.github/workflows/macos.yml`, no harness file. Nothing under .github changes here.

**Part of #253.** The Godot acceptance cases were already covered on main. Unity's
player launcher was the implementation gap; it now uses the same replay sandbox.
New native Unity proof still needs licensed build artifacts and a working Linux
sandbox/display. Web isolation is separate remaining work, as Sean requested.
Neither a missing tool nor a skipped test is positive sandbox evidence.

## Done when, against the starting main

`T` below means `tests.test_replay_sandbox`. Each Godot verdict test runs a clean
sandboxed accept, a public seeded fall-through game that repairs itself only when
its escape succeeds outside the sandbox, and an inside denial leaving the ordinary
ground check failed. No new approval or decision rule is involved.

| Case | Exact evidence on main | Gap and this change |
| --- | --- | --- |
| Socket denied and run not accepted | `T.GameVerdictTest.test_socket_denial_prevents_a_game_from_repairing_itself_into_accept` | Godot already covered. Unity has a new real-process case and the same case on native build artifacts. Native proof pending. |
| Outside write denied and run not accepted | `T.GameVerdictTest.test_write_denial_prevents_a_game_from_repairing_itself_into_accept` | Godot already covered. Unity adds a test-owned outside file, successful outside control and denied player stop. |
| Actual spec/verifier reads denied and run not accepted | `T.GameVerdictTest.test_check_and_verifier_reads_cannot_repair_a_game_into_accept` | Godot already covered. Unity targets the public ground spec and `expectrail/gate/record.py`, not a private set. |
| Environment secret read denied and run not accepted | `T.GameVerdictTest.test_environment_secret_cannot_repair_a_game_into_accept` | Godot already covered. Unity uses a fresh process holding only a known synthetic canary, attempts those exact bytes via /proc, and never prints them. The existing allowlist test also checks the direct environment. |
| Clean frame and trace hashes unchanged on the same runner | `T.SameReplayTest.test_the_clean_game_gives_the_same_hashes_with_and_without` | Godot already covered. Unity adds a nonempty frame-list and exact trace/hash comparison for portable and native players. New real-tool runs pending. |
| CI runs Godot sandboxed | `ci.yml` → **seeded-bugs**, required sandbox module, seeded replays, sample and Run it; `tests.test_ci_gate.IsolationTest.test_the_action_can_require_it_and_this_repository_does` | Already covered. No workflow edit. The same collected module now imports the portable Unity cases; missing Bubblewrap in that required lane fails. Native Unity is a separate proposed manual lane. |

The existing Godot tests were not merely inferred from their names. Read the
successful `seeded-bugs` [job 132950211768 in run 43759283144](https://github.com/Expectrail/Expectrail/actions/runs/43759283144/job/132950211768),
on the merged audit commit `0d2786af0f9bd2362136898a1707cff86e02e8dc`:
all four `GameVerdictTest` cases, both `GameEscapeTest` cases and `SameReplayTest`
are `ok`; **60 tests, 79.868s, OK**, no skips. The log names
`EXPECTRAIL_SANDBOX_TESTS: required`, and later replays use
`EXPECTRAIL_SANDBOX: require`. [Small extracted record](measurements/253-godot-ci.json).
Also read historical #505 job 132783185354: 56 tests, 54.666s, OK, no skips,
including the hash comparison, with the sandbox required. These are existing
runs, not new dispatches and not proof for this patch's new UID/Unity code.

## Other Build/review cases

| Requirement | Current evidence / change |
| --- | --- |
| Godot import and replay both inside | Existing `T.HarnessTest.test_sandboxed_every_engine_start_goes_through_the_sandbox_with_inside_paths_only`; existing real import/replay CI above. |
| Same isolation on the Unity player | New `tests.test_unity_replay_sandbox.UnitySandboxWiring.test_every_player_start_uses_readonly_runtime_inputs_and_private_display`; shared `harness.sandbox.run`, no second sandbox. Real process cases below. |
| No silent fallback; required refuses before game starts | Existing `T.ModeTest` and `T.HarnessTest.test_required_and_impossible_stops_before_the_game_is_touched`; new Unity `test_require_refuses_before_copy_or_player_when_bubblewrap_is_missing`, `test_require_failure_is_never_an_unsandboxed_retry`, `test_auto_fallback_names_why_and_off_never_probes`. |
| Read-only inputs, bounded work/output, time/process limits | Existing `T.CommandTest`, `EscapeTest`, `DiskBoundTest`; Unity sends only its runtime folder, route and map as read-only inputs and uses the same limits/watch. New `PlayerBoundaryTest.test_runtime_input_is_readonly` tests an actual write-open, with an outside control. |
| Output cannot read host data through a planted link | Existing Godot `T.CollectTest`; new Unity `test_hostile_output_links_are_not_followed_even_in_diagnostic_mode` covers run account, trace and frames. Runtime metadata must name the writer's fixed player/game.x86_64 layout, with no links; it cannot select a repository/project directory instead. |
| Record actual network/filesystem/process/tool/version/UID | Shared replay schema and new Unity example; both writers use `box.describe`. UID/GID are now explicit launcher choices and recorded real IDs. `ReplayIdentity.test_explicit_uid_and_gid_are_the_identity_in_the_replay_contract` checks command, writer, strict reader, invalid IDs and legacy records. No evidence grade is raised. |
| Required/zero replay cannot support passing checks | Already fixed by #313: `tests.test_ci_gate.IsolationTest.test_a_record_cannot_count_fewer_replays_than_its_checks_rest_on`. Unchanged. |
| Empty/unknown sandbox account is outside | Already fixed by #313: `tests.test_ci_gate.IsolationTest.test_an_account_must_name_a_tool_the_record_knows`. Unchanged. |
| Kernel user-namespace setting conditional and explained | Existing verify action's condition and docs/ci-gate.md. No action/runner policy changed. The new proposal changes it only on its ephemeral Ubuntu replay job. |
| Aggregate disk growth bounded | #505's shared watch: 4 GiB / 250,000 entries, measured each 0.1 s and after exit. Sparse/unreadable/fast-exit cases already tested; this is a measured bound with possible interval overshoot, not a filesystem quota. |

## Unity implementation and proof limits

`harness.unity.run.run(..., sandbox=None)` and `--sandbox auto|require|off` use
`EXPECTRAIL_SANDBOX` and the same default as Godot. `require` refuses before the
project copy/player command where the real tool/display cannot run. A failure
inside the sandbox never retries outside. `auto` records a diagnostic fallback
reason; `off` explicitly records that containment was turned off.

Build metadata must name the standard `player/game.x86_64` runtime; alternate
directories, traversal, absolute paths and linked executables are refused.
The player executable and its sibling runtime data are mounted read-only at
`/in/player`, with read-only route/map files. The writable project copy is `/game`;
player output is a separate `/out`. A sandboxed player always starts its own
Xvfb; it cannot use the host display. Unity preferences use the sandbox's fresh,
bounded home. Build accounts themselves are bounded, strict regular JSON files; links are
refused before they can be read or copied into evidence.
Only plain run-account/trace/frame files are collected back into
the final run folder. The player cannot write the host-owned replay account.
A failed player has no published `replay.json`.

The new `isolation.uid`/`gid` fields are optional for backward compatibility.
The command explicitly selects those invoking real IDs inside its own user
namespace; the record names them. A namespace UID is not host root authority.
The old record reader still recomputes acceptance using its existing isolation
rule; adding these fields does not grant a grade or clearance.

`tests.unity_sandbox_cases.PlayerBoundaryTest` executes a **portable Python
stand-in for the Unity player protocol**, through real Bubblewrap when available.
It proves OS isolation of that launcher, not that C# compiles or Unity renders.
The new standalone native-player class runs the same five attempts and the clean
hash comparison using **actual** clean/probe player builds. Its C# probe is the
public patch `tests/fixtures/unity-sandbox-probe.patch`; no tracked game source was
edited. The probe requires its attempted capability: when denied it quits with
code 73, and the ordinary runner must refuse it and publish no replay. It is a
failure-path canary, not a detector that rejects every game that ever attempts a
blocked operation. A game can handle an OS denial and continue; the existing
checks decide its behavior.

The native test lane is not a new unified Unity verifier. `adapters.UNITY` still
has no production `verify_run`; `expectrail verify` cannot grant Unity acceptance.
The Unity Editor build remains a separate trusted, licensed activity outside
this player sandbox. `--sandbox` with `--build` is refused rather than silently
claiming to contain the Editor. No license, account, approval or model is used by
these tests. Web/Chromium isolation is not implemented here.

## Local results and exact remaining actions

The before suite on the assigned base is **4,539 tests, 435.088s, OK, 58 skips**,
with no EXPECTRAIL variables. The focused runner/contract/old Unity/CI wiring
check is **102 tests, 19.462s, OK**. The native probe patch applies to a copy and
leaves the game's source digest unchanged; it was **not compiled with Unity**.

Real-tool attempts here are skipped by name: Bubblewrap cannot create a namespace
(`Resource temporarily unavailable`) even outside the command wrapper; the wrapper
also refuses nested UID mapping. `xvfb-run` is absent, and no native Unity build
artifacts are installed. The final configured-Godot attempt has **four named
skips**, not four passes. No kernel setting was changed. The portable/native
classes fail on missing prerequisites when their required CI switch is set.

The exact remaining Sean actions are:

1. Push the reviewed patch and inspect the existing **seeded-bugs** job: all old
   Godot escapes/verdict/hash tests and the six new portable Unity cases must run
   under `EXPECTRAIL_SANDBOX_TESTS=required`, with no portable/tool skips. This is
   also the first real-tool check of the new explicit UID/GID flags.
2. Review/install [253-unity-sandbox.yml.txt](proposals/253-unity-sandbox.yml.txt)
   as `.github/workflows/unity-sandbox-closeout.yml` on main. It is a proposal,
   not an installed or dispatched workflow.
3. Provision the dedicated Linux runner label `expectrail-unity` with an already
   activated **Unity 6000.3.21f1** Editor; set repository variable
   `EXPECTRAIL_UNITY_EDITOR` to that executable. Reuse the protected `unity`
   environment. Do not provide a license/key to the replay job. This workflow
   never activates Unity or reads a secret; its build uses trusted main only.
4. After reviewing the runner/license boundary, run exactly:

   ```sh
   gh workflow run unity-sandbox-closeout.yml --repo Expectrail/Expectrail --ref main -f confirm=true
   ```

   Inspect six native cases with no skips: outside controls succeed, inside
   probes report false and publish no replay, and clean nonempty PNG hashes and
   trace hashes match. Keep `unity-sandbox-closeout` (actual records/traces/frames
   and logs) and the run URL. A successful build or empty test count is not proof.

No workflow was changed or dispatched here. No native-player or sandbox boundary
success is claimed from a skip or from the unit transport. Full suite/export
results are in this change's work log and the handover. Keep #253 open until the
new real-tool/native evidence exists; list web isolation separately for its builder.
