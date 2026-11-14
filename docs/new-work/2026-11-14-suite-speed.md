# Faster suite fixtures without reduced coverage (#334)

## What changed

Built on main `77fa9f06b7ad75edf03123ad6dbf2d711172e5fe`, branch `chatgpt/suite-speed`. Measured every module before edits, then removed repeated fixture construction without changing product code or existing assertion meaning.

- `tests/test_jit_sam_observer.py`: cache immutable compressed PNG bytes by dimensions and seed, with a bounded cache. Every replay still writes independent full-size files. Pixel values, compression level, digests, all frames, all nine replay judgments and every assertion remain unchanged. The unchanged CLI-observer module benefits from the same helper.
- `tests/geometry_fixture.py` (new helper): share serialized real-engine geometry traces only when game content, route bytes, engine identity and harness scripts match. Return a fresh document each time. Distinct scenes still run; no verification result, observer answer or determinism test is cached.
- `tests/test_body_box.py`: obtain geometry rows through the shared fixture; all original body sizes, full-route positions, row counts and assertions remain unchanged.
- `tests/test_ground_under.py`: use that same fixture for repeated scenes already replayed by the body-box tests; keep every distinct scale, offset, platform, gap and source check. The long slope replay and its greater-than-one-hundred supported rows remain unchanged.
- `tests/test_agents.py`: the bounded-retry test uses an existing real PNG as its report-first briefing instead of rendering a new game run. Its stand-in fixer, real verifier, trust check, two-attempt behavior, logs and assertions remain unchanged. Screenshot capture is outside this test's purpose.
- `tests/test_assurance.py`: build a small source repository containing the complete unmodified game (digest checked) and an unrelated-file canary, then create the successful normalization once for read-only checks. Real Git cloning, seed/fix patching, separate candidate trees and bundle generation remain. The repeatability test still compares two independently produced normalizations; relative-output and refusal tests normalize afresh. Existing assertions inspect the shared fixture's actual paths. Parse the fixed workflow inventory once and deep-copy it per policy test; assertions and mutation isolation remain unchanged. OBAAF integration tests retain their original full-repository source.
- `tests/test_suite_fixtures.py` (new tests): add five checks for exact PNG encoding, independent files, fresh trace documents, replay invalidation after scene/route/engine changes and failures not entering the cache. No existing test is replaced or skipped.

## What was run

- Read AGENTS.md, fetched `c169a5e0da304773587304ed47bc8aabcec80da7` and current main, and made a separate worktree so earlier handovers remained intact.
- Full suite before and after through the included timing runner, which delegates to unittest discovery with unchanged order and records exclusive test/fixture time: Before: 3414 tests in 669.349 s, OK (skipped=37). After: 3419 tests in 449.373 s, OK (skipped=37). 32.86% faster locally (219.976 s saved); the 30% target is met. Before and after failing-name lists are both `[]`, with the same 37 skips. All original test names remain; five new fixture tests are added.
- Uninstrumented `python3 -m unittest discover -s tests -t .`: 3419 tests in 434.444 s, OK (skipped=37); 35.09% below the measured baseline.
- Initial focused run of fixtures, recorded observers, retry, normalization and real geometry: 80 tests in 132.563 s, OK. After the final normalization/inventory setup change, fixture and full assurance modules: 33 tests in 3.083 s, OK with the existing eight OBAAF skips. Final full suites include every changed module.
- The first measured after-run was 459.601 s (31.34% faster), but its uninstrumented confirmation took 485.452 s (27.47% below the measured baseline). Retained both first-pass logs and tightened the remaining normalization/inventory setup before the final runs above. Removed only completed synthetic `/tmp/jit-test-*` outputs created by this task, between runs, to keep adequate disk space; no active test output or private data was read or removed.
- An AST audit compares all existing assertion calls, test names and decorators in changed modules; unchanged apart from normalization paths referring to the shared fixture. Protected paths checked against the base. `git diff --check` passes. Patch applies to the exact base, with byte-identical applied files and the real index unchanged.
- Full logs, every module and individual-test timing, the before/after slowest-module table, assertion audit, test-name comparison and runnable measurement script are included in the handover.

## Not done

No product code, workflow, approved spec or bundled game edit. All nine explicitly excluded test files remain unchanged or absent as on the base. No existing test was deleted, skipped, weakened or renamed. Route lengths and frame counts were not reduced.

The orchestrator's real worker/child-process, cancellation, lease-renewal and lost-worker tests keep their waits: replacing those with a fake clock would stop exercising the process interaction. Replay sandbox tests keep real confinement/process checks. Unity's timeout test keeps a real sleeping child and process timeout. Generated-pattern tests keep their large pattern set and fixed digest. JIT repeatability tests keep ten independent executions. Geometry tests retain the full walks needed to cross the gap, step and slope; only duplicate setup data is shared. PNG sizes are retained because the recorded prompt boxes require those coordinates.

These are local Linux wall-time measurements, not a CI timing claim. No macOS/Windows run, GitHub run, paid model call, private/held-out inspection, branch commit or push was performed. Tests create disposable Git fixture history as before. Existing tests exercise synthetic fixtures and the available real Godot engine. #334's published issue describes an older package-install failure; this PR addresses the user's requested test-job speed slice and does not claim to resolve that infrastructure issue.

## Files

- `docs/new-work/2026-11-14-suite-speed.md`
- `tests/geometry_fixture.py`
- `tests/test_agents.py`
- `tests/test_assurance.py`
- `tests/test_body_box.py`
- `tests/test_ground_under.py`
- `tests/test_jit_sam_observer.py`
- `tests/test_suite_fixtures.py`
