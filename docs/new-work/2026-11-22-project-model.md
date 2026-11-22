# Qualify the source-derived rail and movement drafts (#741)

## What changed

One Godot source adapter can draft the two required setup assertions from an authored rail and a pinned out-and-back reference replay. The versioned record makes source and replay provenance available for review. A separate public fixture and controls qualify the pair through the existing evaluator.

## What was run

- `python3 -m unittest tests.test_project_model` initially failed to import the absent authoring module. The separate entry scene mismatch test reproduced silent acceptance before the guard was added. Both passed after implementation.
- The focused model, schema, contracts, new-work, link and evidence tests passed, 76 tests total.
- The checkout authoring command reproduced the checked-in example and both draft bytes.
- The public qualifier used pinned Godot 4.7.2 and ran three independent derivations plus 15 replays across five arms. All replays had complete windows. Both rail offsets failed 3/3, the same-input freeze failed movement 3/3, and the clean and harmless arms passed. All three model and draft derivations matched byte for byte.
- The installed wheel's existing setup review generated a page and completed a clean replay. Its manifest kept both original draft hashes and marked both unapproved.
- The full suite ran 5,994 tests with 81 skipped and one failure. The wheel completeness test found both new authoring modules missing from the package.

## Not done

Distribution of the authoring command requires the packaging allowlist update. The setup review and each spec's approval remain with their existing owners.

## Files

- `bench/project-model/741/` holds the fixture, route, committed controls and qualifier.
- `contracts/project-model.v1.schema.json` and `contracts/examples/project-model.v1.json` define and illustrate the authoring record.
- `expectrail/project_model.py` reads and writes the record and drafts the pair. `expectrail/project_model_godot.py` derives and exercises the reference.
- `tests/test_project_model.py` covers the draft pair, identity checks and unsupported reference evidence.
- `docs/measurements/741-project-model.md` records the public trial and the setup handoff.
