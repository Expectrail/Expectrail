# A missing recorded player-box answer requires review (#823)

## What changed

At frame 119 of the fall-through repair, the unchanged game yielded no player box and the recording lacked the answer requested for the repaired game. The comparison used to discard that lookup failure and the evidence viewer showed Accepted. The gate now records the frame as `no-answer` when a required recording lookup fails on either side. The existing decision reader then blocks an accept. A proved failure can still reject the change.

An answered frame with no box, an engine move and a question deliberately skipped outside gameplay retain their existing meanings. The recording format and the published findings schema use their existing fields and states.

## What was run

- Ran the local sample command on Linux with Godot 4.7.2 and the checked-in recordings. On main `de1ddd65`, `python3 -m expectrail.runit run --sample fall-through-repair --out DIR` answered 134 of 135 questions and wrote `accept`. Its viewer heading was “Accepted”.
- Repeated that command on this change for `fall-through-repair` and `fall-through-bug`. Each answered the same 134 of 135 questions and identified frame 119 as unanswered. The repair returned `needs-review` and the bug returned `reject`. Chromium 156 opened both local evidence reports. Their visible headings, embedded decisions, findings and status documents agreed.
- The new gate regression failed on all three missing-answer cases before the change. The corresponding answered controls accepted. After the change, `python3 -m unittest tests.test_anchor_gate tests.test_anchor_rule tests.test_dodge_vision_ready tests.test_recorded_renderer` passed all 117 tests, including the outside-game rehearsal that skips out-of-play questions.
- The public export scan passed. The full-suite result is recorded on [the tracking issue](https://github.com/Expectrail/Expectrail/issues/823).

## Not done

The two recordings still lack the exact answer. Fresh model inference, deployment and a deployed-service smoke were not run. The visitor-facing regression was originally recorded by the [scheduled repair run](https://github.com/Expectrail/Expectrail/actions/runs/45047712815).

## Files

- `expectrail/gate/anchor.py` identifies a missing recording when the observer returns an error.
- `agents/anchor_rule.py` gives that observation its existing unanswered-frame classification.
- `tests/test_anchor_gate.py` exercises the decision with both the missing and answered observations.
- `tests/test_recorded_renderer.py` checks that missing observations from both sides retain the renderer explanation and require review.
