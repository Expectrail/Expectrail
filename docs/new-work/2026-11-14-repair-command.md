# Repair a rejected verify job (#433)

## What changed

`expectrail repair JOB` reads a completed reject, checks the original game tree and policy, and builds a repair request from its public failing checks. Each attempt starts from the same game. A fixture supplies a patch without running an agent. The live path requires Muse's spend meter and provider gateway. The fixer never receives the verifier’s checkout or the job store.

Every candidate gets a new verify job against the original head with the repair intent. The loop records its attempts and stops on accept, needs-review, an empty fix or the attempt limit. The command saves the patch and prints the record’s review label. The user's checkout is unchanged.

## What was run

- `python3 -m unittest discover -s tests -t .` ran 3,271 tests before and 3,280 after. Both ended in OK with 42 skips and zero failures or errors. Both failing-name lists were empty.
- `python3 -m unittest -v tests.test_repair_command tests.test_package tests.test_orchestrator tests.test_gateway` ran 147 tests, OK with five skips. The separate doctor usage run passed all six tests.
- The first full run found a usage test that required repair to stay planned. Its exact command-list assertion was updated for the built command.
- The six initial command tests failed before implementation.
- The fixture observation in the handover used the bundled fall-through bug and its repair patch. The stand-in observers recorded three failures on the bug and three passes on the fixed copy. The first candidate was accepted and its patch matched the supplied fixture.
- A local check by the builder only, not reproduced in this pull request: on #436's branch, with a zero Muse cap, repair stopped before starting Muse and wrote a spend-cap, needs-review record. No test here exercises #436's meter; the live fixer cannot start from main until #436 lands (`_live_budget` refuses without it).

## Not done

No live fixer, paid observer, real Godot run or workflow dispatch. The base does not include #436. A configured live repair requires its spend meter. The fixture path and an installed command were tested locally.

## Files

- `agents/fixer.py`
- `agents/sandbox.py`
- `contracts/examples/verify-request.json`
- `contracts/verify-request.v1.schema.json`
- `docs/new-work/2026-11-14-repair-command.md`
- `expectrail/cli.py`
- `expectrail/orchestrator/engines.py`
- `expectrail/orchestrator/request.py`
- `expectrail/repair.py`
- `setup.py`
- `tests/test_doctor.py`
- `tests/test_package.py`
- `tests/test_repair_command.py`
