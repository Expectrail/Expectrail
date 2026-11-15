# Missing prerequisites and macOS test portability (#378, #365)

## What changed

Doctor reports optional Playwright Chromium, missing Xvfb/xauth components, and a native macOS display via CoreGraphics. Native drawing/sandbox failures name the appropriate host/session fix. The extensible doctor v1 schema documentation and example, the writer and quickstart evidence reader change together; the optional browser does not block Godot-only readiness. No quickstart command or verdict expectation changes.

Tests check installed engine/cache/native bundle availability without downloads; required CI switches still fail. The exact pinned PATH engine is eligible; a different version is named, never used by accident. Browser bugs remain failures instead of catch-all skips. Download fixtures isolate their cache. Linux-specific shell dependencies and escape controls name why they cannot run elsewhere. The Xvfb stand-ins explicitly test Linux. Parent paths are canonicalised without following the audited final filename. The depth fixture remains deeper than Python's recursion limit on a Mac, and Linux keeps its original size. Glob reference comparisons explicitly request case sensitivity. The Unity environment test holds the actual spawn boundary and requires an empty-env runtime control before treating __CF_USER_TEXT_ENCODING as a native runtime addition. The product allowlist is unchanged.

Read both issues/comments and merged #391, #406, #415. Main already includes cancellation without /proc and safe Bubblewrap namespace probing; no changes to either implementation. The PR body lists each Done-when item and its evidence, including the native-run gap. Existing tests remain; every changed test file and assertion change is explained there.

## What was run

- Required fetch of c169a5e0da304773587304ed47bc8aabcec80da7 and fetch of main; base `89ce6ff6ee8324da03c45be4bbdb944c091289cf`.
- Full suite before and after through the included run-hidden.py: python3 -m unittest discover -v -s tests -t ., with Godot, bwrap, Chromium and display tools hidden from PATH, display variables removed, and fresh engine/browser caches. Before: 3543 tests, 5 failures, 1 errors, 46 skips, 346.024 s. After: 3548 tests, 0 failures, 0 errors, 40 skips, 319.980 s.
- Compared failure/error names, including subtests, not just totals. All six baseline failures/errors were the download fixture inheriting EXPECTRAIL_TOOLS; none remains. Final skip names/reasons are in failure-comparison.json and the verbose log. The skip count decreases because class prerequisite skips replace opt-in per-method skips, not because an assertion was dropped.
- Focused final doctor/tool/quickstart run: 67 tests, OK (one real-engine prerequisite skip). Package and Unity tests: 59, OK. Earlier broad focused run: 190 tests, OK (13 prerequisite skips). Path/reader regressions: 23 tests, OK. Linux with sys.platform=darwin: 3 tests, OK (one Linux-only control skip), not native macOS.
- #415 historical CI run 43527696828 was read: completed/success; relevant capture-smoke, agents-sandbox, web-capture, test and package jobs/steps succeeded. This is evidence for the merged fix, not a CI run of this patch.
- Earlier focused and full attempts are retained: wrong PATH engine selection (4.6.3), an installed-doctor expected-list mismatch, symlink-audit/quickstart-reader mismatches, and two disk-full cascades. These were not silently excluded. Sources stayed intact; completed generated test fixtures/baseline extracts were removed for disk space. A subsequent full run was green before the final native-message and keyless-environment regressions were added; the final full run above includes both.
- git diff --check; scope/retained-test audit; patch application and byte checks; ZIP checksums. No commit or push.

## Not done

Native macOS was not run. CoreGraphics and __CF runtime behavior need a Mac; stand-ins are not that evidence. Successful real Godot 4.7.2, browser and sandbox integrations for this patch need a capable Linux host/CI. A macOS CI runner decision remains needs-sean: workflow changes were explicitly out of scope. No issue closure or native-support claim. No paid model, held-out/fresh material, game or approval edit, protected file change, or GitHub write.

## Files

- `contracts/doctor.v1.schema.json`
- `contracts/examples/doctor.json`
- `docs/new-work/2026-11-14-macos-missing-tools.md`
- `expectrail/doctor.py`
- `tests/test_adapters.py`
- `tests/test_apt_install.py`
- `tests/test_auto_route_engine.py`
- `tests/test_check_pages.py`
- `tests/test_doctor.py`
- `tests/test_downloads.py`
- `tests/test_event_input.py`
- `tests/test_ground_under.py`
- `tests/test_missing_tools.py`
- `tests/test_orchestrator.py`
- `tests/test_package.py`
- `tests/test_platform_tools.py`
- `tests/test_replay_sandbox.py`
- `tests/test_route_patterns.py`
- `tests/test_second_project.py`
- `tests/test_unity_harness.py`
- `tests/tool_requirements.py`
- `tools/quickstart.py`

## The guard's finding on #479 (architect)

- `expectrail/doctor.py`, `chromium()`: any exception from the optional browser probe, on import or
  on launch, is now a `missing` check with a fix and `required: False`. Before, only Playwright's
  `Error` and `OSError` were caught, so a plain `Exception` (the driver's "Connection closed") or a
  broken install crashed the whole `doctor` command. Browser stderr is still never copied.
- `tests/test_platform_tools.py::test_any_failure_of_the_optional_browser_probe_is_missing_never_a_crash`
  fails on #479's head and passes here.
- A correction to #479's description: the raw logs and the `run-hidden.py` runner it mentions are in
  the builder's handover, not in this pull request. The hidden-tools counts are the builder's run.
