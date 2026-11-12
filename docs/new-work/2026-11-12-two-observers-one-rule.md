# The gate can judge every check with two observers, and nothing passes on the engine's record alone under that rule (#251, #327)

## What changed
The verification the gate and the orchestrator's `godot` engine share (`expectrail.gate.verify.run_gate`)
takes a rule for which observers judge.

- **The rule `both`** (Sean's decision of November 12, #327). Every approved check is judged by the
  engine's record and by a visual observer over the frames the replay captured.
  `expectrail.gate.record.combine` joins the two: a pass needs both to pass, a failure on either is a
  failure, and anything else (the visual observer could not decide, gave no answer, or was not asked)
  needs review. With no visual observer the seeded bug is still rejected and nothing is accepted, and
  the reasons say so. The visual observer is not asked about a check the engine's record already
  fails. Held-out routes are judged by the same rule, with no answer cache kept for them.
- **The visual observer** is `expectrail/observers.py` (`FramesObserver`): the existing SAM adapter
  (`agents.sam_observations.from_replay`) over the captured frames, with the engine's ground line as
  the reference where the trace has one, as `agents/verifier.py` does. Every way it can fail is "no
  answer". It is not in the wheel, which holds nothing that holds a model key.
- **The record** (`contracts/findings.schema.json`) says which rule judged (`observers`, with the visual
  observer's name, provider and model) and, under `both`, what each observer said on each side of each
  check and the SHA256 of the visual observer's answer (`observed`). The answer itself is written to
  `observations/<arm>/<route>/<spec>.visual.json`. The reader recomputes each row from `observed` and
  refuses a row that passes without the visual observer's pass. A record without the block is read as
  `engine-only`, and an `engine-only` record is written without it. The first push wrote the block
  on every record, and this pull request's own gate comment came back "the evidence could not be
  used: a property is not allowed here": the comment job runs main's reader, which did not know the
  block. An engine-only record is now byte-for-byte what it was, so a reader older than the writer
  reads it.
- **The rule `engine-only`** is what the gate did before, unchanged, and is still the default: the
  pull-request gate and `expectrail verify` use it. The comment and the
  review page have a "Judged on" line that says a verdict rests on the engine's record only.
- The orchestrator's engine takes the rule and the observer (`GodotGate(rule=, visual=)`) and tells the
  job its `observing` and `evaluating` phases.

- **A pass has to cover the check** (third push, after the merge guard's review). The guard showed
  that under `both` a visual pass on 5 frames, or on 1, of a 120-frame window was an accept, as was
  an answer cut to its first frame, an answer naming another replay, and a 20-tick log of a 240-tick
  route. The gate now counts the frames the window should have from the route's ticks, not from
  what an observer returned. The engine's pass needs every tick of the route and every frame of the
  window; the visual observer's pass needs the replay to have captured every frame of the window and
  the answer to hold every one (`reaches`, which passes on one frame, needs the whole capture only);
  an answer about another replay is no answer; and when the gate cannot tell the count, nothing
  passes. The reason carries the count ("the visual observer saw 4 of 120 frames of the check's
  window"). `engine-only` is unchanged; the same question for it is #357.
- **Held-out frames are not sent to the visual observer** unless the caller passes
  `heldout_frames_to_visual=True`, which nothing does. Without it no held-out check passes under
  `both` (a failure on the engine's record still counts), and the reasons say so. Whether held-out
  frames may go to a model's provider is Sean's decision; this makes the default the side that
  sends nothing.

## What was run
- `python3 -m unittest tests.test_two_observers`: 37 tests, OK (inside the full run below). They use a stand-in replay (a position
  log with the ground line and the camera, and real PNG frames) and a stand-in model that answers in
  SAM 3.1's wire format, as `tests/test_sam.py` does. These are scripted answers, not recordings of the
  live model. The real observations code, evaluator and record reader judge them.
- With the rule loosened on purpose (a pass when the visual observer was not asked), 11 of the
  first 35 tests fail (run before the spend-cap test was added).
- The full suite, `python3 -m unittest discover -s tests -t .`, on the branch rebased on main 25d8585:
  2,295 tests, 26 skipped, OK (after the second push's change; 2,294 before it).
- Third push (the merge guard's review): `python3 -m unittest tests.test_two_observers`: 49 tests, OK.
  The guard's seven rows are tests in `CoverageTest`, with the cases beside them (an answer missing
  one frame, an answer with no replay named, a route twice as long, a trace with no tick rate). With
  the three new checks taken out on purpose, 15 of the 49 fail. The full suite on the branch merged
  with main at 3bc07d9: 2,406 tests, 26 skipped, OK.
- Not run: a real Godot replay through the rule `both`. That the harness writes one row for every
  tick and one frame for every other tick is read from `harness/godot/expectrail_harness.gd` and from
  the recorded replays in the repository (240 ticks, 120 frames), not measured here. If a real replay
  comes back one frame short, the result is needs-review with the count, not a wrong pass.

## Not done
- The reader still takes the record's word for what the visual observer said: it does not read the
  stored answer back or count its frames (#254's trusted job; `visual_gap` is callable on a stored answer).
- The count of frames a route should have uses the tick rate the trace states. A game that misstates
  it is not caught by this.
- Whether held-out frames may be sent to a model's provider: Sean's decision. Off until then.
- No live model has judged through this path, and no command constructs a visual observer: nothing
  here can start a paid call. An observer made with the real client is held to the run's spend cap
  (`EXPECTRAIL_SAM_USD_CAP`, merged in #343 while this was being built); a request the cap stops is
  "no answer". The month's total (#267) is not built, and wiring the observer to a command waits
  for it and for Sean.
- `expectrail verify`, `expectrail sample` and the pull-request gate still judge by `engine-only`.
  Changing the default changes what a first run and every pull request comment say; that is #327's
  second step (the architect session's) and, for pull requests, #254.
- A spec about nothing drawn is needs-review under `both`. The approved field that would let the
  engine's record alone decide such a spec is not built; it is a person's decision on the spec.
- The score floor the older verifier keeps on the clean replay (`samMinScore`) is not carried over.
- The judge ladder's fallback order (judge again, then Glimmer, then a person) is not wired here: a
  model that does not answer is needs-review at once.
- Still left on #251: the engine is picked from `ENGINES` by name, not through `harness/adapters.py`,
  and `harness.run.run` still falls back to the bundled game when given none.
- The capability ledger is unchanged: no mode is claimed that was not there.

## Files
`expectrail/observers.py` (new), `expectrail/gate/verify.py`, `expectrail/gate/record.py`,
`expectrail/gate/comment.py`, `expectrail/gate/page.py`, `expectrail/orchestrator/engines.py`,
`contracts/findings.schema.json`, `contracts/examples/findings-both-observers.json` (new),
`tests/test_two_observers.py` (new), `tests/test_package.py` (one line: why the observer is not in the
wheel), `docs/ci-gate.md`, `docs/contracts.md`, `docs/orchestrator.md`.
