# Sandbox close-out: Unity player and exact Godot evidence (#253)

## What changed

Audited the issue body, all 14 prior comments plus the claim, linked PRs #300,
#304, #312, #313, #505, #534, and current main at
`d877ddb647161e4af28aa554e7886d91e1b83f5b`. The existing Godot verdict/hash tests
already cover the Done when list; fetched their actual successful hosted log.
The [case table](../replay-sandbox-closeout.md) separates those existing proofs
from this change's unmeasured native Unity path. Web stays separate at Sean's request.

Unity player replay now delegates to `harness.sandbox.run`: read-only runtime,
route/map, private display, allowlisted environment, bounded work/output and the
existing process/time/disk limits. Auto/off fallback is recorded; require refuses
before copying/starting a player when unavailable, and never retries a failed
sandbox outside it. Plain-output collection refuses links, including the run
account; failed players publish no replay. Metadata must name the fixed runtime
layout, cannot point at an absolute/parent/linked executable, and is itself
strictly read as a bounded regular JSON file, never through a link. The Editor build is separate
and not sandboxed; an explicit replay sandbox flag cannot silently run a build.

Contracts first: optional real launch UID/GID in the replay schema, a new Unity
example, explicit launcher IDs, both writers and strict-reader tests. Legacy
records remain readable. Existing acceptance/evidence grades are not promoted.
The capability row is corrected to distinguish recorded Godot integration from
unit-tested Unity code and missing native proof; rendered page stays in sync.

Added portable real-process and native-artifact cases to the existing
`tests.test_replay_sandbox` collection, with outside controls, five denied
capabilities (the original four plus runtime write-open) and exact clean
frame/trace comparisons. Portable tests are explicitly not a Unity engine.
The native C# canary is a patch applied only to copies; it has not been compiled
here. The native tests require actual licensed artifacts and retain evidence
only when the dedicated test environment asks. No model or approval is involved.

Checked #574 before editing harness code and again during work: its head
`2bbaecf25f3b02625dd68342a32189bf1f79718e` lists only the macOS workflow file.
Neither changed harness file overlaps that list. No .github file changes.
The complete new native workflow is a proposal under docs/, for Sean to install.

## What was run

- Required historic fetch succeeded once:
  `git fetch --no-tags --depth=1 origin c169a5e0da304773587304ed47bc8aabcec80da7`.
- Before changing source: `python3 -m unittest discover -s tests -t .`, no
  EXPECTRAIL variables: **4,539 tests, 435.088s, OK, 58 skips**. Exit 0.
- Red against starting main: the first six new unit cases give **6 errors**:
  the old runner has no sandbox argument, and no explicit identity fields/flags.
  Raw `red-unit.log` retained. This is missing-interface proof, not real OS proof.
- The first focused run had **1 failure in 58 tests**:
  `tests.test_unity_harness.RunnerTest.test_the_player_gets_the_route_map_seed_and_window_it_needs`.
  It expected the old direct output path. The test now expects private staging;
  final exported outputs and every other argument/assertion stay checked.
- Focused compatibility: **102 tests, 19.462s, OK** (Unity runner, new wiring,
  identity schema/writer/reader, old sandbox command/modes, gate isolation reader
  and existing Unity workflow tests). Added proposal shape test: **1 test OK**.
- With numpy and PIL import/discovery blocked: **64 tests, 14.457s, OK, 2 skips**.
  Both real-process classes name the unavailable Bubblewrap/display/native inputs;
  they are not passed boundary cases. All unit transports and old Unity protocol
  cases run without those image libraries.
- Final runner/metadata checks: **51 tests, 16.899s, OK**.
- Final full suite: `python3 -m unittest discover -s tests -t .`, no EXPECTRAIL
  variables: **4,551 tests, 392.478s, OK, 60 skips**, exit 0. No failing test.
- `python3 -m expectrail.capabilities render` and `check`: exit 0. Proposal YAML
  parsed; every embedded shell step passes `bash -n`. Final packaging/scope/export
  checks are recorded in the handover. Supplemental final ledger/proposal/work-log
  checks: **51 tests, 1.317s, OK**.
- `python -m agents.export_scan bench docs README.md apps --paths error`: **764
  files, 0 errors, 0 warnings, exit 0**. The forbidden spent blind directory
  entry was temporarily moved outside the scan roots and restored in a finally
  block, without reading any of its contents.
- Existing hosted evidence, fetched read-only:
  [43759283144 / seeded-bugs job 132950211768](https://github.com/Expectrail/Expectrail/actions/runs/43759283144/job/132950211768),
  merged audit commit `0d2786af0f9bd2362136898a1707cff86e02e8dc`: all four exact
  `GameVerdictTest` cases, `GameEscapeTest`, `SameReplayTest` OK; **60 tests,
  79.868s, none skipped**, sandbox required. [Compact source excerpt](../measurements/253-godot-ci.json).
  Also reread #505's earlier real-tool job (56 tests OK). Neither run covers
  this patch's explicit IDs or new Unity code.

A rerun was inadvertently started before an intermediate suite had ended. Both
were stopped; the partial/mixed log is retained and counted as neither pass nor
fail. The final 4,551-test suite ran alone to completion in a separate log. The
earlier completed 4,550-test after run is also retained as intermediate evidence.

Local real-tool attempts, including an attempt outside the command wrapper:
Bubblewrap cannot create a namespace (`Resource temporarily unavailable`);
the wrapper fails nested UID mapping. `xvfb-run` and native Unity artifacts are
absent. With the pinned Godot path configured, the explicit real-case command
records **4 named skips**. It ran no inside boundary case. No stand-in is relabelled
as a sandbox/Unity success; no system setting was changed to force a result.

Guard: test change intended (#253)

Existing test changes: the old Unity fake-player tests explicitly select off
(their shell stand-in names a script outside the mounted runtime; they never
proved OS containment), its argv test expects separate staging, and the sandbox
account equality now requires UID/GID. New real boundary cases cover containment.
No assertion was deleted or loosened; required real-tool lanes cannot pass by
skipping the portable cases. Native cases have a separate required switch.

## Not done

No native Unity compilation or native/portable real sandbox boundary success in
this environment. No new Godot hash/verdict run with this patch's ID flags. Sean
must push and inspect the existing required seeded-bugs lane, then review/install
and deliberately run the proposed native lane on a dedicated already-licensed
Editor runner. Exact actions and the dispatch command are in the close-out audit.
The proposed lane and its Editor/runtime dependencies have not run here.

No live model calls, spend, new account/credential, dispatch, push, GitHub write,
workflow edit, approval edit or tracked game-source edit. No actual held-out,
fresh or blind content was read. `verify.py` and `anchored.py` are unchanged.
Web isolation is explicitly separate remaining work; the Unity Editor is outside
this replay boundary, and unified Unity verify is still unavailable. #253 stays
open for real native/changed-launcher evidence and the separately scoped web work.

## Files

- `contracts/replay.schema.json`, new `contracts/examples/replay-unity-isolated.json`.
- `harness/sandbox.py`, `harness/unity/run.py`.
- New `tests/test_unity_replay_sandbox.py`, `tests/unity_sandbox_cases.py`, and
  `tests/fixtures/unity-sandbox-probe.patch`; existing `test_replay_sandbox.py`
  and `test_unity_harness.py` with the intended changes above.
- `docs/replay-sandbox-closeout.md`, `docs/replay-sandbox.md`, small CI excerpt,
  native workflow proposal, capability JSON/generated page, and this work log.
- Full raw local logs, before/after results, patch/PR text and integrity checks
  are in the handover, not main.
