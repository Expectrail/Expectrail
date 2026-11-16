# Replay sandbox acceptance audit (#253)

Audited main/task base `51b3264f0867eff61ccfeab735f262cc026835b0` on 2026-11-15,
after #304, #312, their follow-ups and #505. **#253 cannot close:** Unity and web
replay remain outside this sandbox. The four Godot boundaries already exist; this
patch fills gaps in tests that connect the denied operation to the gate's verdict.
No sandbox runtime, decision rule, schema or approval change is needed for those gaps.

“Covered” below means a named test contains the assertion, not merely that some test
mentions the capability. A test being present on main is separate from it running
locally. `T` means `tests.test_replay_sandbox`; `G` means `tests.test_ci_gate`;
`R` means `tests.release_gate.gate_sandbox`.

| “Done when” case | Test on main at the audited base | Status on main | This patch |
| --- | --- | --- | --- |
| Game opens a socket: blocked **and not accepted** | `T.GameEscapeTest.test_inside_the_game_reaches_none_and_the_replay_says_it_was_isolated`; `R.EgressTest.test_in_the_isolated_class_a_change_cannot_reach_a_port_and_is_rejected` (both have outside controls) | Covered, through real Godot and a verdict test | Adds headless `T.GameVerdictTest.test_socket_denial_prevents_a_game_from_repairing_itself_into_accept` |
| Game writes outside scratch: blocked **and not accepted** | `T.GameEscapeTest.test_inside_the_game_reaches_none_and_the_replay_says_it_was_isolated` proves denial, with outside control; it does not judge a verdict | **Missing** combined denial/verdict test | Adds `T.GameVerdictTest.test_write_denial_prevents_a_game_from_repairing_itself_into_accept` |
| Game reads specs or verifier: blocked **and not accepted** | Same `GameEscapeTest` explicitly tries a spec and verifier; `R.PrivatePathTest.test_in_the_isolated_class_a_change_cannot_read_a_private_file_and_is_rejected` judges a generic private-file attack | **Missing** exact spec/verifier denial/verdict test | Adds `T.GameVerdictTest.test_check_and_verifier_reads_cannot_repair_a_game_into_accept` |
| Game reads an environment secret: blocked **and not accepted** | Same `GameEscapeTest` proves parent-environment file denial and an empty direct secret; no verdict or positive read of the fake secret's bytes | **Missing** secret-byte denial/verdict test | Adds `T.GameVerdictTest.test_environment_secret_cannot_repair_a_game_into_accept` |
| Clean game's frame and trace hashes unchanged, sandbox on/off, same runner | `T.SameReplayTest.test_the_clean_game_gives_the_same_hashes_with_and_without` compares all frame hashes, trace hash and engine identity and requires nonempty captures | Covered | Unchanged; historical CI run verified, not rerun locally without `xvfb-run` |
| CI runs Godot replay sandboxed | `.github/workflows/ci.yml`, `seeded-bugs`: sandbox tests with `EXPECTRAIL_SANDBOX_TESTS=required`; every seeded replay and sample verification with `EXPECTRAIL_SANDBOX=require`; `G.IsolationTest.test_the_action_can_require_it_and_this_repository_does` checks repository wiring | Covered | No workflow changes or dispatch; read historical CI evidence only |

The new tests use actual headless Godot, actual bubblewrap, the ordinary harness and
`run_gate`'s explicit engine-only rule. Their replay callback disables PNG capture
but returns real trace bytes, tree digest and isolation account; it never supplies
observations, results or a verdict. No model is asked, and no default observer rule
is weakened. Each test has three real replays:

1. The unchanged clean game inside the sandbox accepts.
2. A seeded fall-through game repairs its collision mask only if its escape works;
   outside the sandbox the escape succeeds and the repaired game accepts.
3. Inside the sandbox the attempt reports failure, the bug remains, and the ordinary
   position check fails: the verdict is reject. The saved findings reader rechecks it,
   with one judged route and one required sandboxed replay.

All paths are public source or test-owned canaries. The environment control launches
a fresh process with exactly one fake variable, then tries to read those exact bytes
through `/proc/PID/environ`. It never dumps an environment or reads a real secret.
Original game files and approved specs are copied unchanged; only temporary game
copies get an autoload and the existing public seeded patch.

## The two #312 record-reader gaps

Both were already closed on main. They were checked, not reimplemented.

- `G.IsolationTest.test_a_record_cannot_count_fewer_replays_than_its_checks_rest_on`:
  required plus zero replays cannot support passing checks. `check_consistency` counts
  distinct judged head/base routes and a lower bound for aggregate private checks,
  excluding replays that failed to finish or were not applicable. Undercounting fails
  even if the sandbox was not required; a crash with no finished replay remains readable.
- `G.IsolationTest.test_an_account_must_name_a_tool_the_record_knows`: an empty sandbox
  dictionary contributes zero sandboxed replays and yields needs-review when required.
  Both `contracts/findings.schema.json` and `contracts/replay.schema.json` require tool
  and version on a non-null sandbox; `check_record` applies the closed schema before
  consistency/decision checks. The current examples already name a tool/version.
  No schema, example, writer or reader change is necessary.

The review's other point, the action's user-namespace setting on a self-hosted runner,
is already described in `docs/ci-gate.md`'s `require-sandbox` row. The action changes
that setting only when required; this audit changes neither the action nor the setting.

## Red evidence and local limits

The handover includes the mutation driver and all four red logs. The tests themselves
are unmodified during each mutation; only a process-local replacement of
`harness.sandbox.command` deliberately removes the relevant existing enforcement:
network namespace, outside-folder exclusion, spec/verifier exclusions, or the complete
namespace launcher for the secret test. Each selected test then fails its assertion
that the operation was denied. Every red has exactly one assertion failure, no error
and no skip. These are regressions against **existing** enforcing code, not claims
that this patch introduces a new runtime defence.

For the secret case, removing PID isolation alone was insufficient: another existing
namespace boundary still denied the read. The recorded red removes the whole launcher
and translates only the harness's known mount paths to host paths. It reads only the
fresh canary process. Production files are never rewritten by the mutation driver.

Real bubblewrap 0.12.0 works outside the command wrapper here. The wrapper's nested
probe fails with a read-only uid map; it is not evidence that the host lacks the tool.
The locally cached official Godot 4.7.2 binary was SHA-512 verified in the preceding
work and reused here. No `EXPECTRAIL_*` variable is set for the final full suite;
individual tests patch their own cache/canary settings and restore them.

`xvfb-run` is absent, so the clean frame-hash comparison cannot run locally. Its
existing test passed in real bubblewrap 0.9.0 in historical #505 CI:
[run 43704707400, seeded-bugs](https://github.com/Expectrail/Expectrail/actions/runs/43704707400/job/132783185354).
The downloaded log records the original Godot controls, denial test and hash comparison
as `ok`, followed by `Ran 56 tests ... OK` with none skipped. This was a read of an
existing run, not a new workflow execution or evidence for the new tests running in CI.
The current workflow still requires the tool and comparison; it has not been changed.

## What remains

- Unity player isolation and its real-process tests: **missing, out of scope**.
- Web replay isolation and its real-process tests: **missing, out of scope**.
- The original Build section also asks for explicit UID reporting; `replay.json`
  currently records tool/version, network, filesystem, process isolation, environment
  policy and limits, but no UID field. **Still missing**; outside this Done-when test
  slice. No stronger capability claim is made here.
- Local frame-hash rerun needs `xvfb-run`; historical CI proves that existing test, not
  this machine. No installation workaround or system-policy change was made.

The default remains `auto`/diagnostic, with recorded fallback reasons; `require` and
`isolated` refuse a missing sandbox. Required/outside never accepts (existing record
and orchestrator tests cover that). This audit does not upgrade evidence grades or
change default CLI policy. Total disk use is already bounded by #505; see
[replay-sandbox.md](replay-sandbox.md), `DiskBoundTest` and `R.DiskQuotaTest`.
