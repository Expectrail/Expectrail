# Godot import aborts: what the public logs show (#494)

Reviewed on November 16, 2026. The evidence cutoff below is expressed in UTC.
This is an investigation, not confirmation of the native crash's cause.

[#498](https://github.com/Expectrail/Expectrail/pull/498) merged at
2026-11-15 06:13:43 UTC. Through 2026-11-16 20:51:06 UTC, the requested jobs
contain **no recorded real Godot abort**. The recurring `Godot SIGABRT ... ok`
line comes from a passing test with a simulated process failure.

## Inventory

The [job-by-job inventory](godot-import-abort-inventory.csv) links all 681 logs
read: 673 from runs created after the merge, plus eight from runs crossing the
merge-time boundary. It includes successful jobs, since a failed cache warm can
be logged in a job that ultimately succeeds. There were no unread logs;
transient log-fetch errors succeeded on a second read. Every post-merge run in
this inventory had one attempt. The handover also retains API run/job metadata,
matched lines, and the two full logs quoted below.

| Job | Post-merge logs read | Real aborts | Jobs with real aborts | Mocked SIGABRT descriptions |
| --- | ---: | ---: | ---: | ---: |
| test | 163 | 0 | 0 | 163 |
| package | 163 | 0 | 0 | 0 |
| seeded-bugs | 163 | 0 | 0 | 0 |
| capture-smoke | 163 | 0 | 0 | 0 |
| outside-trial | 21 | 0 | 0 | 0 |

The eight boundary logs also contain no real abort, and two contain the mocked
test description. There is consequently no post-merge abort step or stderr tail
to report in this interval. This count is not a claim about future runs, missing
artifact-only diagnostics, or other jobs. Private-job logs were not opened.

Searches covered `Godot import aborted`, `SIGABRT`, signal 6, `Aborted`,
`std::system_error`, `pthread_create` and `terminate called`. A second full pass
also checked exit status 134, returncode -6, core-dump and abort spellings. Matches were read
in context; test descriptions were not counted as engine failures. The six failed
`test` jobs, five failed `package` jobs and one failed outside trial were included.

## The line that still appears

In [run 43933682499, test job 133532505154](https://github.com/Expectrail/Expectrail/actions/runs/43933682499/job/133532505154),
step `Run python -m unittest discover -s tests -t . -v`, the log says:

```text
Godot SIGABRT on clean-replay must not leave verification.json unwritten. ... ok
```

This is the docstring of
`tests.test_agents.VerifierDecideTest.test_harness_clean_abort_falls_back_and_still_decides`,
which verbose unittest prints. The test mocks the harness and injects
`CalledProcessError(-6, ..., stderr="SIGABRT")`; no engine causes that failure.
It asserts that the candidate is rejected, files are written and the baseline
fixture fallback is explicitly identified. The docstring now starts
`Simulated SIGABRT (stand-in)`. Its assertions and behaviour are unchanged.

A real abort from the current import helper instead logs
`harness: Godot import aborted; stderr tail: ...`, then raises the process error.
The existing `tests.test_harness.HarnessTest.test_editor_import_is_serial_and_restores_replay_settings`
checks propagation on both direct and sandbox invocation paths, with the
original project settings restored. An abort is not returned as a successful
import by that helper.

## The original real failure

The [original package job 132609787637](https://github.com/Expectrail/Expectrail/actions/runs/43647942916/job/132609787637),
step `The whole suite on Python 3.12`, records two SIGABRTs on **November 14**,
before #498:

| Phase | Evidence in the job log | Stderr |
| --- | --- | --- |
| Cache warming | 22:28:00 UTC: headless `--import` died with `Signals.SIGABRT: 6`, then fell back to direct import | Not recorded |
| Direct import | `SlopeTest.setUpClass` error, traceback printed at 22:33:56 UTC: the separate headless `--import` died with `Signals.SIGABRT: 6` | Not recorded |

The original job failed; it did not accept an aborted import. Its two invocations
used different disposable project paths. This proves a native abort occurred,
but neither stderr nor a native stack establishes why.

## Cause and limits

#498 disables parallel asset import on the disposable copy, restores the original
project configuration afterwards, and logs a bounded, quoted stderr tail on
SIGABRT. Its [upstream report](https://github.com/godotengine/godot/issues/125245)
describes intermittent parallel cold-import crashes on the pinned engine in a
different project using Mono. Parallel import is therefore a plausible historical
cause; it is not proven for Expectrail. Resource exhaustion or another native
failure cannot be distinguished from these logs. No observed recurrence does not
prove the serialization caused the improvement.

No retry is added here. #494 permits it as a last resort only when import is known
to be safe to repeat. Import executes project code and can leave partial changes;
repeating it needs a safety argument and must not turn an aborted import into a
pass. These logs establish neither a remaining engine defect nor that a retry
is needed. The native-cause part of #494 remains open.

If another actual abort occurs, retain the job URL, step, complete quoted stderr
tail and associated command/traceback. Those are the evidence needed to choose
a cause-specific fix or a safe, bounded retry. No workflow change or dispatch is
needed to clarify the current test output.

## Local check on the current harness

With Godot 4.7.2, the original `SlopeTest` class passed **20/20** times with
fresh import caches while full-suite discovery ran alongside it. Both original
assertions ran each time: 40 test executions, no skips, no abort. The driver
and per-iteration logs are in the handover. This is a current-tree check, not a
paired before/after experiment and not a reproduction of the native fault.
#498's historical before/after load counts remain separate evidence.
