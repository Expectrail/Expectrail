# Verification judges with vision (#379)

## What changed

Every registered orchestrator engine now uses `both` with a `FramesObserver`, so verify,
sample and the app through verify need both observers to pass. Missing MODEL_API_KEY or
EXPECTRAIL_SAM_USD_CAP stops the job as needs-review with a diagnostic naming the fix, before
any replay or model request. Doctor requires both settings, reports the cap, and withholds the
key. Tests use scripted SAM 3.1 answers from tests/test_two_observers.py, never a live model.

The wheel includes the frame observer, SAM adapter and its supported client dependencies, without
agents.keys or the fix loop. The sandbox applies the harness's game environment allowlist too.
Job status carries the findings record's observers block; report describes it in plain words.
The job contract, example, writer and reader changed together. Docs name the required settings,
the no-settings behavior, and the cost example in docs/sam.md (up to $0.60 for both prompts over
one 120-frame run).

Guard: test change intended (#379). Existing engine-only fixtures explicitly construct that
Gate; the registry assertions now require both. Doctor tests assert the required configuration.
No test was deleted or newly skipped, and no assertion was weakened.

## What was run

- Required fetch: `git fetch --no-tags --depth=1 origin c169a5e0da304773587304ed47bc8aabcec80da7`.
  This is the older #191 commit, without AGENTS.md or the task's modules. Work is based on
  main at 70caaa0 after reading its AGENTS.md. The initial test attempt on the old commit was
  stopped; it is not the baseline comparison.
- Baseline: `python3 -m unittest discover -s tests -t .`: 2,707 tests, 2 failures, 2 errors,
  31 skipped, in 444.655 seconds. It ran in a separate unmodified checkout of the same main commit.
  This environment reproduces four of #365's previously reported 15 cases: xvfb-run is missing
  and the web fix loop cannot run its Chromium.
- Post-change: the same discovery command, 2,711 tests, 2 failures, 2 errors, 31 skipped,
  in 379.812 seconds. Compared the `(failure/error type, failing test name)` sets from the
  unittest summary blocks: identical; no new or removed failures. The four added tests pass.
  The identical failing names are:
  - `tests.test_event_input.EventInputTest.setUpClass` (error)
  - `tests.test_web.FixLoopTest.test_a_real_fix_is_accepted_with_the_private_sessions_mounted` (error)
  - `tests.test_web.FixLoopTest.test_a_bug_its_checks_cannot_see_is_not_detected_without_sam` (failure)
  - `tests.test_web.FixLoopTest.test_without_the_private_sessions_nothing_is_accepted` (failure)
- The first post-change discovery run was stopped after README's new cap setting exposed the
  capability ledger's switch inventory. The cap was added to the ledger, its orchestrator row
  updated, and the page regenerated; the final full run starts from that corrected tree.
- `python3 -m unittest tests.test_capabilities`: 46 tests, OK.
- `python3 -m unittest tests.test_verify_vision tests.test_doctor tests.test_package tests.test_replay_sandbox`:
  80 tests, OK, 9 skipped. The stand-in game process records the environment the real harness
  supplied with MODEL_API_KEY set on the verifier; the key is absent. Sandbox command building
  is checked independently, including when its input environment contains the key.
- `python3 -m unittest tests.test_engine_from_adapter tests.test_orchestrator tests.test_verify_vision`:
  137 tests, OK.
- `git diff --check`: passed.

### Validated and reconciled by the architect session

Separately from the runs above: Ubuntu, Python 3.13.18, Godot 4.7.2 present, main at `ada0dd3`
(the patch was made against `70caaa0`).

- `git apply --3way` applied every file except two, which conflicted with work merged since:
  `setup.py` (kept both sides: `app` and `app_page` from #376 beside `observers` and `providers`, and
  `agents.anchor_rule` and `agents.sam_anchor` from #373 in the wheel, as the handover asked) and
  `tests/test_package.py` (the three "imported only with a visual observer" exceptions removed,
  since those modules now ship; `agents.keys` stays out).
- The first full run with the change: 2906 tests, 5 failures and 1 error. Two causes, both in tests:
  `tests/test_app.py` (merged after this patch was made) built `GodotGate(replay=FakeReplay())`,
  which now judges with both observers and, with no key, ends needs-review; it now passes
  `rule='engine-only'` explicitly, as #379 says tests must. And
  `test_default_rule_uses_frames_and_status_and_report_name_both_observers` found the model's
  answers already in the shared cache other tests had filled, so nothing was asked; it now has a
  cache of its own (`XDG_CACHE_HOME`).
- After both: the full suite on unchanged main ran 2902 tests, OK (27 skipped); with this change,
  2906 tests, OK (27 skipped). No failures or errors on either side.

## Not done

No live model call or model spend. No GitHub write, commit or push; Sean does those.
No change to expectrail/app.py, expectrail/app_page.py or tests/test_app.py.
#373 was still open when work started, so agents.anchor_rule and agents.sam_anchor are not
packaged here. Decision B is unchanged. The two-job PR vision gate (#254), monthly aggregate
budget (#267) and unrelated environment failures (#365) remain outside this issue.

## Files

- `README.md`
- `contracts/doctor.v1.schema.json`
- `contracts/examples/doctor.json`
- `contracts/examples/verify-job.json`
- `contracts/verify-job.v1.schema.json`
- `docs/capabilities.json`
- `docs/capabilities.md`
- `docs/ci-gate.md`
- `docs/install.md`
- `docs/new-work/2026-11-13-verify-with-vision.md`
- `docs/orchestrator.md`
- `expectrail/doctor.py`
- `expectrail/orchestrator/cli.py`
- `expectrail/orchestrator/engines.py`
- `expectrail/orchestrator/runner.py`
- `expectrail/orchestrator/sample.py`
- `expectrail/orchestrator/store.py`
- `harness/sandbox.py`
- `setup.py`
- `tests/test_app.py` (the stand-in engine made explicitly engine-only, by the architect session)
- `tests/test_doctor.py`
- `tests/test_engine_from_adapter.py`
- `tests/test_orchestrator.py`
- `tests/test_package.py`
- `tests/test_second_project.py`
- `tests/test_two_observers.py`
- `tests/test_verify_vision.py`
- `tests/test_viewer.py`
