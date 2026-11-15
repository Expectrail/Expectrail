# Config lane

A self-written test fixture, not an outside project. `Actors/Avatar` is a 24 × 24 body
and owns the moving camera. `Lookalike` uses the same sprite without being the player.
The viewport is 360 × 240; the 120-tick route holds the project's `move_right` action.

The config is a draft, with no approved checks. No verification accept is claimed for it.
`tests.test_project_audit` checks the read-only proposal offline and, with Godot installed,
replays both full-path and group bindings and checks named setup refusals. The real tests
need no display or model. They never change this fixture in place.
