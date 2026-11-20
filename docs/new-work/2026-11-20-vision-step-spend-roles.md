# The Run it recording step and the outside vision judge send only to the vision model (#267)

## What changed
The spend-cap audit (`tools/spend_cap_audit.py`) follows imports, so it listed two steps that set only
the vision model's cap (`EXPECTRAIL_SAM_USD_CAP`) as possibly reaching senders whose caps they do not set:

- `run-it-record.yml::record` (`python -m expectrail.runit record`): Muse and spec. This is the step a
  person dispatches to record a Run it sample's vision answers (#265). If it reached a capped sender
  without its cap, it would stop partway through a paid recording.
- `outside-vision.yml::judge` (`python -m tools.outside_vision judge`): spec.

Both were `unreviewed` in `tools/spend_cap_gaps.json`. They are now reviewed by running the code. The new
`tests/test_vision_step_spend_roles.py` runs each command as its step runs it:

- The environment holds a made-up key and exactly the caps the step sets. Tests read those caps from the
  workflows, and also check that neither step picks another vision backend or a month ledger, so these
  tests fail first if a workflow changes.
- `urllib.request.urlopen`, the network floor of every HTTP sender, is replaced by a recorder. It answers
  the vision model's address as the stand-in model of `tests/test_two_observers.py` would, and refuses
  every other address.
- The spend meter is a fresh one that records every hold asked for, held or refused. `spend.require_cap`
  is recorded too.

Results:

- `runit.record`, with no client given, so it builds the live vision client the step would build: for
  every recording target the workflow offers (`clean`, `fall-through-bug`, `fall-through-repair`,
  `gate-combat`), the recording is written with answers. Every request went to the vision model's
  address, and no other role was held or asked for its cap. A test holds the workflow's target list to
  those four.
- `tools.outside_vision judge`, with the stand-in vision model put where the command builds its client:
  pinned, broken and harmless are judged accept, reject and accept. Nothing reached the wire, and no other
  role was held or asked for its cap.
- Controls: without the vision cap, the recording sends nothing and the judge refuses before building a
  client. With a cap worth one image, the recording sends exactly one request.

The three listed caps now say `not sent:` with the reason and the test. No workflow changed. The
recording step's `cannotTell` line stays: it is the audit's own limit, since it does not follow the
order of a script's commands.

## What was run
- `python3 -m unittest tests.test_vision_step_spend_roles`: 9 tests, OK.
- Four mutations, each made and then reverted, each caught:
  - a spec hold added to `runit.record`: 4 failures;
  - a swallowed request to another address added to `runit.record`: 6 failures;
  - a swallowed `require_cap("muse")` added to `runit.record`: 4 failures;
  - a swallowed spec hold added to `tools.outside_vision judge`: 1 failure.
- `python3 -m tools.spend_cap_audit --check`: exit 0, 48 steps listed, matching the recorded list.
- `python3 -m unittest tests.test_spend_cap_audit tests.test_vision_step_spend_roles`: 72 tests, OK.
- Full suite on the branch from main at 8d503f2: 5,725 tests, OK, 75 skipped.

## Not done
- The other `unreviewed` steps in `tools/spend_cap_gaps.json`, for their workflows' owners. Vision's caps
  are #327's.
- The live schema, error and timeout checks, and comparing the holds with a bill (Sean).
- No workflow was dispatched and nothing was spent. The stand-in model is not the live model.

## Files
- `tests/test_vision_step_spend_roles.py` (new)
- `tools/spend_cap_gaps.json`
- `docs/new-work/2026-11-20-vision-step-spend-roles.md` (new)
