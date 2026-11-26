# Qualify the source-derived rail and movement drafts (#741)

## What changed

One Godot source adapter can draft the two required setup assertions from an authored rail and a pinned out-and-back reference replay. The versioned record makes source and replay provenance available for review. A separate public fixture and controls qualify the pair through the existing evaluator. The packaging owner's two allowlist entries include the common model and Godot adapter in the wheel. [Packaging handoff](https://github.com/Expectrail/Expectrail/issues/741#issuecomment-7194535869)

## What was run

- `python3 -m unittest tests.test_project_model` initially failed to import the absent authoring module. The separate entry scene mismatch test reproduced silent acceptance before the guard was added. Both passed after implementation.
- The focused model, schema, contracts, new-work, link and evidence tests passed, 76 tests total.
- The checkout authoring command reproduced the checked-in example and both draft bytes.
- The public qualifier used pinned Godot 4.7.2 and ran three independent derivations plus 15 replays across five arms. All replays had complete windows. Both rail offsets failed 3/3, the same-input freeze failed movement 3/3, and the clean and harmless arms passed. All three model and draft derivations matched byte for byte.
- The installed wheel's existing setup review generated a page and completed a clean replay. Its manifest kept both original draft hashes and marked both unapproved.
- Before the packaging patch, the wheel completeness test failed on the rebased branch because both authoring modules were missing.
- Built the wheel from the combined branch with `pip wheel --no-index --no-deps --no-build-isolation` and installed it in a new virtual environment. The installed authoring command and the five public control arms passed as expected with Godot 4.7.2. The 15 replays produced 45 complete verdicts with zero indeterminate outcomes. Bubblewrap could not set its UID map, so the replays used local host fallback.
- Full discovery with packaging tests required passed. `python3 -m unittest discover -s tests -t .` ran 6,048 tests in 954.906 seconds, with 80 skips. The first run reported a Debian test setup error because the environment lacked the pinned `installer` build dependency. The rerun used `installer==1.1.0` from a temporary directory.

## Not done

The setup review and each spec's approval remain with their existing owners.

## Files

- `bench/project-model/741/` holds the fixture, route, committed controls and qualifier.
- `contracts/project-model.v1.schema.json` and `contracts/examples/project-model.v1.json` define and illustrate the authoring record.
- `expectrail/project_model.py` reads and writes the record and drafts the pair. `expectrail/project_model_godot.py` derives and exercises the reference.
- `setup.py` includes both authoring modules in the wheel.
- `tests/test_project_model.py` covers the draft pair, identity checks and unsupported reference evidence.
- `docs/measurements/741-project-model.md` records the public trial and the setup handoff.
