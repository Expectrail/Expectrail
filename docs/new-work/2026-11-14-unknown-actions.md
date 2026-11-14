# Name the route inputs the game does not have (#417)

## What changed

The Godot trace lists missing input actions once each in `unknownActions`. A defined action with no key or pad binding remains valid. The gate makes an affected route needs-review and puts the action names in the job reasons. A missing field in an older trace means the gate cannot tell whether the route was exercised. A separate valid route can still reject a change.

The unreachable-route probe now runs as a normal release test and requires needs-review with the missing action named.

## What was run

- `python3 -m unittest discover -s tests -t .` ran 3,251 tests before and 3,256 after. Both runs ended in `OK (skipped=42)`. Neither log contained a failing or erroring test name.
- All 19 focused tests passed. The offline checks covered engine-only and both-observer decisions, invalid or absent action lists, an unreachable base, and a failure on another route.
- With headless Godot 4.6.3, the public event-input fixture produced an empty list for its defined inputs. Adding repeated unknown inputs and an event beyond the last tick yielded the two distinct missing names.
- A headless replay of the sample with every smoke input renamed completed through the orchestrator with exit 2, needs-review, and `teleport_through_wall` in its job reasons.

## Not done

The displayed release probe skipped locally because xvfb-run was missing. The headless observation used an injected replay, no captured frames, and the locally installed Godot. The pinned-engine release probe still needs the Linux run. No paid observer was called.

## Files

- `contracts/examples/trace-unknown-actions.json`
- `contracts/trace.schema.json`
- `docs/new-work/2026-11-14-unknown-actions.md`
- `expectrail/gate/verify.py`
- `harness/godot/expectrail_harness.gd`
- `tests/coverage_replays.py`
- `tests/release_gate/controls.py`
- `tests/release_gate/gate_coverage.py`
- `tests/test_anchor_gate.py`
- `tests/test_event_input.py`
- `tests/test_release_gate.py`
- `tests/test_two_observers.py`
- `tests/test_unknown_actions.py`

## Architect run

Linux, Python 3, on main at `6993726` (#428) with the patch applied (it was built on `8083215`; it applied cleanly with `git apply`, no conflicts). Godot 4.7.2.stable.official.ed1daf0bf from `harness/get_godot.sh` (SHA-512 checked), under `xvfb-run`.

- `python3 -m unittest discover -s tests -t .`: `Ran 3287 tests`, `OK (skipped=31)`.
- `EXPECTRAIL_ENGINE_TESTS=required python3 -m unittest tests.test_body_box tests.test_event_input tests.test_ground_under tests.test_pause_input tests.test_second_project tests.test_auto_route_engine tests.test_unknown_actions`: `Ran 69 tests`, `OK`, none skipped.
- `EXPECTRAIL_RELEASE_GATE=required python3 -m unittest -v tests.release_gate.gate_coverage`: `Ran 6 tests`, `OK`. `test_a_route_whose_inputs_the_game_does_not_have_is_not_clearance` passed on the pinned engine (it is no longer an expected failure).

Not run: the handover's two reproduction scripts (`writer_check.py`, `job_observation.py`), which are not part of the change, and the rest of the release gate suite. No paid observer was called and no workflow was dispatched.
