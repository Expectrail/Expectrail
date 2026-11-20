# Distinguish the simulated import abort from a real CI failure (#494)

## What changed

Read #494 and #498 and their comments. Audited 673 requested public job logs from
163 CI and 21 outside-trial runs created after #498 merged, plus eight requested
logs from runs crossing the merge time. Found no real Godot abort in that
interval. All 163 post-merge `test` logs print a passing mocked test's SIGABRT
description. The original package failure contains two real SIGABRTs on November
14, before #498, without stderr or a native stack.

Changed only that test's docstring to say `Simulated SIGABRT (stand-in)`.
Assertions, import settings, failure propagation and verdicts are unchanged.
Published the investigation and a source link for every audited job. The exact
native cause remains unknown; no speculative retry was added. See
[the investigation](../godot-import-aborts.md).

## What was run

- Required historic-base fetch, then fetched current main and the claimed branch.
  Base: `ba050a770f6010c430b51c6a93cf1e81d2cccff5`.
- Full suite before: 4,530 tests, OK, 58 skips, zero failures/errors, 572.471s.
- Focused regression and harness tests: 16 passed. Captured the old and new
  verbose test descriptions; the injected failure and assertions did not change.
- Loaded 129 tests from the changed test module and harness tests with NumPy and
  Pillow unavailable.
- Current-tree real Godot 4.7.2: the original SlopeTest class passed 20/20 times
  alongside full discovery, on fresh caches: 40 test executions, no skips or
  abort. This is not a paired before/after load experiment.
- Full suite after: 4,530 tests, OK, 58 skips, zero failures/errors, 601.170s.
  Failing-test names before and after are both `[]`; counts and skips match.
  All 20 load-probe iterations ran during the after-suite.
- Export scan: 763 files, no errors or warnings. Whitespace check passes;
  the patch is verified against the base in a separate Git index.

## Not done

No confirmed native cause or reproduction of the historical crash. The lack of
an observed abort does not prove serialization cured it. No retry, live model,
spend, dispatch, workflow change, push, GitHub write or product commit.
The browser part and its earlier load runs are recorded in #498; this change
does not redo or claim them. #494 remains open pending native diagnostic evidence.

## Files

- `tests/test_agents.py`: one docstring identifies the existing simulated abort.
- `docs/godot-import-aborts.md`: count, provenance, evidence and limits.
- `docs/godot-import-abort-inventory.csv`: one source link per audited job log.
- This work log. Full logs, metadata and apply instructions are in the handover.
