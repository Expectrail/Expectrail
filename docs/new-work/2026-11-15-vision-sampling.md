# Optional outside vision sampling (#330)

## What changed

Added --vision-every to the outside judge, default 1. The anchored observer samples only its
point questions; the gate independently opts in, retains complete engine/capture coverage and
does not relax explicit spec coverage. Findings and the human summary name the stride. Three
consecutive negative samples still fail, with their real-frame span stated. No spec was edited.

The outside judge reuses exact successful PNG/kind/prompt answers within one invocation. Provider
errors are not cached and point prompts are never treated as box prompts. Other recording clients
keep reuse disabled by default. Schema, example, writer and reader changed together.

## What was run

Read AGENTS.md, #330 and all comments, #481, and the successful capture/judge jobs of run
43652198623. Required fetch and current main fetch; base 6b04f87e7e801c3c34d5deca3bc5d67e4cdb237c.
An initial baseline exhausted disk (3663 tests, 1 failure, 2 errors, 38 skips); its log is retained.
Removed identified completed synthetic game-copy fixtures, without reading protected paths,
and reran the baseline. Before: 3663 tests, 0 failures, 0 errors, 38 skips, 594.515s. After: 3675 tests, 0 failures, 0 errors, 38 skips, 614.835s. Failure/error-name lists are both empty; no new failure.

Focused tests: 139 tests, OK (42.320s). Patch application to the named base, byte comparison and ZIP integrity were checked. No existing test is changed, removed or skipped.
Replayed the downloaded public outside capture through the real judge with its recorded answers:
uncached/capped baseline reconstructs 802 requests / 800 answered images; cached stride 1 asks the
recording 448 times (429 answered, 19 absent); stride 4 asks 187 times (168 answered, 19 absent).
All three give pinned/tinted accept and broken/hidden reject. This is offline evidence, not live cost.
Raw per-phase accounting, logs and request counts are in the handover.

## Not done

No live model, spend, dispatch, outside-project rerender, commit, push, GitHub write or approval. No claim about
other games or new capture bytes. Sampling can miss defects shorter than the stride; default 1
is unchanged. The workflows expose no new input. The capped recording cannot answer the hidden
variant's 19 box prompts; those remain unknown. No forbidden file or approved spec was changed.

## Files

- contracts/findings.schema.json
- contracts/examples/findings-sampled-vision.json
- expectrail/anchored.py
- expectrail/recorded.py
- expectrail/evaluator.py
- expectrail/gate/verify.py
- expectrail/gate/record.py
- tools/outside_vision.py
- tests/test_vision_sampling.py
- docs/outside-projects.md
- docs/new-work/2026-11-15-vision-sampling.md
