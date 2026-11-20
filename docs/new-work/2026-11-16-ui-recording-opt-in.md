# Record UI integers only for requesting trace specs (#285, PR #573 rework)

## What changed

Reworked fetched `chatgpt/285-repro-audit` head `021bbbc1a388fa0947d81d188d0861671541bba1`.
The previous handover's local worktree is preserved separately. Sean pushes; no GitHub writes.

The harness's existing `--name=value` argument path now carries the UI request, like optional
configured role bindings. `harness.run(..., trace_specs=...)` derives it from a relation reading
`ui_integer_at_end` or a same-route `signal_compare` reading it on either side. Default replays
neither call the UI scene walker nor add a key. No new route/config/environment mechanism.
JIT passes active applicable specs per probe and uses the same request for candidate fingerprints.
Discovery passes applicable specs, recaptures an existing probe if a new spec first needs UI data,
and carries the request into reproduction replays. An offered signal or general measurement is
not a request. Counter rules, thresholds, schemas, baseline records and policy authority are unchanged.
The public counter test now requests recording through the spec it evaluates.
The branch also lacked main's already-merged integer viewport serialization. Carried that one
line from main `ec0919b60c03abf033ef79a996880300658e6887`: Breakout otherwise differed only
by `[360.0,640.0]` versus `[360,640]`. No trace was normalized to hide that difference.
The first full suite then caught an unshipped trace-module import in the bundled harness.
Moved the selector into the already-bundled harness module; kept the packaging test unchanged.

## What was run

- Final full suite: `python3 -m unittest discover -s tests -t .`: **4576 tests, OK, 41 skipped**, 1026.312 seconds, no EXPECTRAIL_* variables set.
- Focused/package checks: **96 tests OK**, 32.148 seconds. Without numpy/PIL: **4,613 tests load, zero import errors; 96 focused/package tests OK**, 35.587 seconds.
- Public counter: requested by its evaluated spec; clean 5 twice, stuck 0, doubled 10; actual evaluator returns pass/pass/fail/fail.
- Raw-byte parity: **16/16 pairs identical**, all 32 traces omit uiIntegers. Eight cases (bundled pinned/fall-through, three outside pinned/broken pairs), both headless and rendered. Frozen main ec0919b60c03abf033ef79a996880300658e6887; Godot 4.7.2, rendered OpenGL3/llvmpipe. See [generated hashes](../ui-recording-parity.md); both raw files and replay metadata are in the handover. Breakout uses its existing menu-only route, not a new gameplay result. Sandbox off: diagnostic parity only.
- Red controls: before request propagation, argument/planning tests fail; before discovery propagation, both planner cases fail. Removing the default recording guard makes the real-engine no-key regression fail. Logs are included.
- The initial parity check caught main's integer viewport serialization difference; stopped that preliminary capture/suite, aligned the existing main line, froze the source, then ran final comparisons and suite. No trace normalization or existing assertion was used to hide the difference. The first full suite then caught the unshipped trace-module import; moved the shared selector into the bundled harness module and retained the packaging test.
- Export scan: final changed files and handover, zero errors/warnings. Patch applies to PR #573 head and reconstructs the final files byte for byte. No model/dispatch/spend.

## Not done

No new live reproduction rate; #285's audit limitations and Sean's measurement steps remain.
No model call, spend, dispatch, push, PR/comment, approval, workflow edit or game-source edit.
No held-out, blind or fresh-set content used. This patch is on top of PR #573's branch head.

## Files

`harness/run.py`, `harness/godot/expectrail_harness.gd`,
`expectrail/jit/run.py`, `expectrail/discovery/run.py`; new `tests/test_ui_recording_request.py`,
updated `tests/test_trace_ui_integer.py`; `docs/jit.md`, `docs/repro-audit.md`, the generated
`docs/ui-recording-parity.md`, this log.

Guard: test change intended (#285). The existing counter test explicitly requests the reading
through its evaluated spec and retains all original value/hidden-menu assertions, plus actual
pass/fail evaluation. No assertion is relaxed and no existing test is skipped or removed.
