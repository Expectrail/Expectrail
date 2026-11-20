# Read negative visual observations in a configured game (#700)

## What changed

A public Godot repair restored collision but left the sprite fully transparent. The engine passed,
and the visual observer stopped with a schema error. The configured game generated v1 observations.
Its dependency-free reader could read ordinary detections but raised an exception on the first
negative answer. [Hosted repair trial](https://github.com/Expectrail/Expectrail/actions/runs/44731209248/job/136271132534)

The reader now enforces the existing observation schema’s conditional branches, exclusive minimum,
combined constraints and local references to the detection schema. An empty answer and an answered
size or position mismatch each have their own requirements. Invalid evidence still produces
needs-review. References outside the current schema, cycles and unknown schema keywords raise errors.

## What was run

- Before the change, the two new observation tests produced eleven schema errors and one gate
  assertion failure. A valid negative visual answer reached the gate as no-answer.
- `python3 -m unittest tests.test_observation_timeline tests.test_anchored_observer tests.test_clipped_player tests.test_ci_gate`
  ran 196 tests with one skip and zero failures or errors. On a trusted capture timeline the
  engine passed, the calibrated no-match evidence failed from frame 0 and malformed negative
  evidence yielded needs-review. The two schema readers agreed on eleven valid and malformed cases.
- The same anchored-observer gate regression passed under `python3 -S` with the optional
  JSON Schema package absent. The observer received a completed empty answer from the stand-in
  client on each of the six captured frames.
- The full and dependency-free validators both accepted a saved observation document of 120
  frames with 120 size-mismatch entries from the [public capture run](https://github.com/Expectrail/Expectrail/actions/runs/43652198623).
- After the required history fetch, `python3 -m unittest discover -s tests -t .` ran 5,593
  tests in 593.731 seconds with 78 skips and zero failures or errors.
- `python -m agents.export_scan bench docs README.md apps --paths error` scanned 1,257 files
  with zero errors or warnings.

## Not done

A fresh configured app trial with the updated reader must record the actual verdict on the
transparent repair. The archived observations and the gate regression exercise the reader locally.

## Files

- `expectrail/gate/record.py`
- `tests/test_observation_timeline.py`
- `docs/new-work/2026-11-20-negative-observations.md`
