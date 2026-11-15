# Inspect a Godot game and draft its bindings and first route (#260)

## What changed

Inspect reads the starting scene, its instances and the input map without
starting Godot. Init writes a draft route. A unique player and texture yield
a draft project config that the existing reader can use. When a binding is
unresolved, the review file preserves the known fields and names what a
person must supply. Both commands ship in the wheel.

## What was run

The installed commands ran outside the checkout on copies of the bundled game,
kinematic-character and Dodge the Creeps. `python3 -m tests.check_onboarding_games`
checked all three. Each command exited zero.

| Game | Inspect, seconds | Init, seconds | Output |
| --- | ---: | ---: | --- |
| Bundled platformer | 0.039922 | 0.042505 | Config and route |
| kinematic-character | 0.041068 | 0.036633 | Config and route |
| Dodge the Creeps | 0.049875 | 0.035144 | Route and review draft with four candidate player images |

The measurements include command startup. The check also compared all files
and directories before and after inspection. The focused command ran 57 tests
across `tests.test_init_inspect`, `tests.test_package`, `tests.test_auto_route`
and `tests.test_project_config`. All passed. The Dodge-shaped regression first
failed on the earlier draft. That draft also failed the two wheel-inclusion tests.

`python3 -m unittest discover -s tests -t .` ran 3,568 tests before and 3,574
after. Both ended in OK with 51 skips and no failures or errors.

## Not done

A person must confirm bindings, try the route and approve the intended checks.
Human review time was not measured. No gameplay verification or runtime
visibility measurement was part of the timed setup. Hosted CI was not run.

## Files

- `contracts/examples/project-draft.json`
- `contracts/project.v1.schema.json`
- `docs/new-work/2026-11-14-draft-project-inspection.md`
- `docs/project-config.md`
- `expectrail/cli.py`
- `expectrail/onboarding.py`
- `expectrail/project_config.py`
- `expectrail/route.py`
- `setup.py`
- `tests/check_onboarding_games.py`
- `tests/test_init_inspect.py`

## Architect's change on integration

- When every binding resolves, `init` writes the draft to the live `expectrail.project.json`
  (`draft: true`), and nothing in verification read that flag: unreviewed bindings decided what the
  engine measured, and a change could be accepted on them (the new test accepts on #260's head).
  `expectrail/gate/verify.py` now counts a draft config as a check problem, like a changed config:
  the decision is at most needs-review, and a failing check still rejects.
- `tests/test_ci_gate.py`: `test_a_draft_config_from_init_is_never_the_ground_for_an_accept` (a
  draft base and head: needs-review with the reason; the same config without `draft`: no such reason).
