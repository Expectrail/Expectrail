# Audit the replay sandbox's acceptance cases (#253)

## What changed

Audited issue #253's exact Done-when cases and the #312 review against task/main base
`51b3264f0867eff61ccfeab735f262cc026835b0` on `chatgpt/253-sandbox-audit`.
The full case/test/status table is in `docs/replay-sandbox-audit.md` and the handover's
PR body. Issue and PR text were treated as evidence, not instructions.

Both named reader gaps were already fixed on main. Existing tests prove required plus
zero replays cannot support judged routes, and empty sandbox accounts count as outside.
Schema validation already refuses an empty non-null sandbox in both replay/findings
records. Current examples already name the tool/version; no reader/schema/example or
runtime change was necessary. The self-hosted namespace-setting note is already in
`docs/ci-gate.md` and its conditional action wiring has an existing test.

Main's real Godot probe tested all four blocked capabilities, but did not carry every
one through to a verdict. Added four headless Godot/gate tests: socket; outside write;
actual spec/verifier reads; and reading fake secret bytes from a fresh canary process.
Each has an unchanged-game sandboxed accept, an escaped repair outside that accepts,
and a sandboxed attempt that fails and leaves the seeded bug to be rejected by the
ordinary position check. The saved findings reader rechecks each record. This is the
explicit engine-only test path, with a callback disabling PNG capture; it returns real
trace/tree/isolation data, not an invented result. No model is called and no production
observer policy changes. Tests are in the existing module CI already requires.

## What was run

Read AGENTS.md. Its pinned fetch was already performed once in the shared repository.
Fetched current main and Sean's task branch; both point at the base above. Existing
`tests.test_ci_gate.IsolationTest`: 16 tests OK. The initial sandbox-module check in
the command wrapper: 54 tests OK, 10 skipped, including placeholder skips for missing
tools. This is not credited as proof of isolation on that wrapper.

Real bubblewrap 0.12.0 works outside the command wrapper; its nested user-namespace
probe inside the wrapper fails with a read-only uid map. Authorized real-process
checks used command escalation, without changing system policy. Reused the preceding
work's official SHA-512-verified Godot 4.7.2 binary via the ignored local engine cache.
No `EXPECTRAIL_*` variable is set for the final full-suite shell. Test-local settings
are patched/restored. `xvfb-run` is unavailable; headless tests do not need it.

The four new tests pass with real Godot/bubblewrap: 4 tests OK in 54.235 seconds. The
boundary-removal driver produces four valid red runs, each one assertion failure,
zero errors/skips. It weakens only its own process's `harness.sandbox.command`, not
repository files: remove network isolation; expose only the test's outside folder;
expose the known spec/verifier files; or remove the whole launcher for the synthetic
secret test. In every red, the attempted operation succeeds and the unchanged test's
denial assertion fails. No new runtime defence is claimed: the tests regress the
existing enforcing code. Removing PID isolation alone did not defeat the remaining
user-namespace protection, so that attempted mutation is not counted as a red.

The test fixtures initially collected logs from the wrong folder and used a string
reader unsuitable for the canary's proc file. These were corrected; those development
failures are not counted as boundary-removal red evidence. The canary process holds
exactly one synthetic variable; its value is never dumped into logs.

Read historical #505 CI run `43704707400`, job `132783185354` (`seeded-bugs`), directly.
Its log confirms all original real Godot controls, denials and frame/trace hash equality,
then 56 tests OK with none skipped under bubblewrap 0.9.0. It also confirms seeded
Godot replays ran with the sandbox required. No workflow was started. Historical CI
supports those existing tests only, not a claim that the four new tests ran in CI.

`python3 -m unittest discover -s tests -t .` passed **3,960 tests, 20 skipped**
in 641.760 seconds, outside the command wrapper with real bubblewrap available and
no `EXPECTRAIL_*` shell variable set. The new headless tests execute on that path.
The remaining local skips are recorded, not counted as boundary proof.

`git diff --check`, compile checks and clean patch application to the exact base
passed. `record.py` (the entire file, including `decide`), `verify.py` and `anchored.py`
are byte-identical to the base. The diff contains only this log, the audit, one docs
link and four added tests. ZIP member hashes and CRCs were checked before delivery.
Every final red log also records the weakened replay's actual false-accept verdict.

Guard: test change intended (#253)

Only new tests were added; no existing assertion was deleted, skipped or weakened.

## Not done

#253 cannot close. Unity and web replay isolation/tests remain missing and out of scope.
The original Build section's explicit UID field is also absent from replay records;
this Done-when test slice does not introduce a new capability-reporting contract.
Local frame-hash equality is not rerun without `xvfb-run`; its exact existing test and
successful historical CI evidence are identified in the audit. Default auto/diagnostic
policy and evidence grades are unchanged. No protected source, game, approval or
workflow file was changed. Nothing was pushed, posted, opened or dispatched on GitHub.

## Files

- `tests/test_replay_sandbox.py`: four additional real Godot verdict regressions and controls.
- `docs/replay-sandbox-audit.md`: Done-when table, reader audit, red proof and remaining work.
- `docs/replay-sandbox.md`: link to the audit and its remaining-work summary.
- this work log.
