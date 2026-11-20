"""Metamorphic checks (#675, piece 3): mirror the inputs, judged over the clear window only."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from expectrail.contracts import ContractError, validate_v1
from expectrail.jit import metamorphic
from expectrail.trace.evaluator import MIRROR, MIRROR_SIGNALS, evaluate
from tests.test_trace_evaluator import episode, spec

REPO = Path(__file__).resolve().parents[1]
PAIRS = [["move_left", "move_right"]]
G = 0.15  # gravity: the fall speeds up by this much a tick


def op(signal="player_dx_px", left="a", right="b", tol=None):
    return {"type": "metamorphic", "transform": "mirror_x", "pairs": PAIRS, "signal": signal,
            "relation": MIRROR_SIGNALS[signal], "toleranceAbs": metamorphic.TOLERANCE[signal] if tol is None else tol,
            "left": left, "right": right}


def run(side, *, n=200, press=10, release=150, speed=2.5, wall=None, jump_at=None, v0=6.0, ceiling=None,
        enemy=None, land_dy=0.0, eid=None):
    """A player that walks ``side`` (+1 right, -1 left) from x=400 on a floor at y=600.

    ``wall``: the x distance at which it stops dead. ``jump_at``: a jump press, a parabola of initial speed
    ``v0``. ``ceiling``: the rise at which the jump is stopped dead. ``land_dy``: lands this far below
    (positive) or above the floor it left. ``enemy``: an enemy at this (dx, dy) from x=400, y=600."""
    xs, ys, floors = [], [], []
    x, y, vy, on = 400.0, 600.0, 0.0, True
    for t in range(n):
        if press <= t < release:
            x += side * speed
            if wall is not None and abs(x - 400.0) > wall:
                x = 400.0 + side * wall
        if jump_at is not None and t == jump_at:
            vy, on = -v0, False
        elif not on:
            vy += G
            y += vy
            if ceiling is not None and 600.0 - y > ceiling:
                y, vy = 600.0 - ceiling, 0.0
            if y >= 600.0 + land_dy and vy > 0:
                y, vy, on = 600.0 + land_dy, 0.0, True
        xs.append(x)
        ys.append(y)
        floors.append(on)
    action = "move_right" if side > 0 else "move_left"
    inputs = [{"tick": press, "action": action, "pressed": True}, {"tick": release, "action": action, "pressed": False}]
    if jump_at is not None:
        inputs += [{"tick": jump_at, "action": "jump", "pressed": True},
                   {"tick": jump_at + 4, "action": "jump", "pressed": False}]
    rows = [{"tick": t, "player": [xs[t], ys[t]], "onFloor": floors[t], "facing": side,
             "enemies": [[7, 400.0 + enemy[0], 600.0 + enemy[1]]] if enemy else [], "projectiles": []}
            for t in range(n)]
    return episode(rows, inputs=sorted(inputs, key=lambda i: i["tick"]), eid=eid or ("r" if side > 0 else "l"))


def judge(signal, left, right, tol=None):
    s = spec(op(signal, tol=tol))
    s["origin"] = "AUTO_RELATION"
    return evaluate(s, left, right)


class Relations(unittest.TestCase):
    def test_a_symmetric_walk_negates_and_passes(self):
        v = judge("player_dx_px", run(+1), run(-1))
        self.assertEqual(v["result"], "pass", v)
        self.assertEqual(v["metrics"]["left"], -v["metrics"]["right"])

    def test_a_slower_walk_to_the_left_fails(self):
        v = judge("player_dx_px", run(+1), run(-1, speed=2.0))
        self.assertEqual(v["result"], "fail", v)
        self.assertIn("should negate", v["evidence"][0]["detail"])

    def test_no_walk_to_the_left_at_all_fails(self):
        self.assertEqual(judge("player_dx_px", run(+1), run(-1, speed=0.0))["result"], "fail")

    def test_a_higher_jump_on_one_side_fails_equal_height(self):
        left, right = run(+1, jump_at=60), run(-1, jump_at=60, v0=7.0)
        self.assertEqual(judge("max_rise_px", left, right)["result"], "fail")
        self.assertEqual(judge("max_rise_px", left, run(-1, jump_at=60))["result"], "pass")

    def test_each_equal_signal_passes_on_a_mirrored_jump(self):
        for signal in ("max_rise_px", "airborne_ticks", "air_jumps"):
            with self.subTest(signal=signal):
                v = judge(signal, run(+1, jump_at=60), run(-1, jump_at=60))
                self.assertIn(v["result"], ("pass", "not_exercised"), v)
        self.assertEqual(judge("airborne_ticks", run(+1, jump_at=60), run(-1, jump_at=60))["result"], "pass")


class ClearWindow(unittest.TestCase):
    def test_a_wall_on_one_side_ends_the_window_before_it(self):
        v = judge("player_dx_px", run(+1), run(-1, wall=100.0))
        self.assertEqual(v["result"], "pass", v)
        self.assertLess(v["metrics"]["clearToTick"], 60)
        self.assertTrue(any("sideways speed changed with no change of input" in d for d in v["diagnostics"]))

    def test_without_the_clear_window_the_wall_would_be_a_false_failure(self):
        far = dict(MIRROR, horizontalJoltPx=1e9)
        with mock.patch.dict("expectrail.trace.evaluator.MIRROR", far):
            self.assertEqual(judge("player_dx_px", run(+1), run(-1, wall=100.0))["result"], "fail")

    def test_a_slow_side_is_still_caught_before_the_wall(self):
        self.assertEqual(judge("player_dx_px", run(+1), run(-1, speed=2.0, wall=100.0))["result"], "fail")

    def test_a_ceiling_ends_the_window_and_the_rise_compares_before_it(self):
        v = judge("max_rise_px", run(+1, jump_at=60, ceiling=40.0), run(-1, jump_at=60))
        self.assertEqual(v["result"], "pass", v)
        self.assertTrue(any("departed from gravity" in d for d in v["diagnostics"]), v["diagnostics"])

    def test_landing_at_another_height_ends_the_window(self):
        v = judge("airborne_ticks", run(+1, jump_at=60), run(-1, jump_at=60, land_dy=-20.0))
        self.assertEqual(v["result"], "pass", v)
        self.assertTrue(any("landed" in d for d in v["diagnostics"]), v["diagnostics"])

    def test_an_enemy_close_by_ends_the_window(self):
        v = judge("player_dx_px", run(+1, enemy=(30.0, 0.0)), run(-1, enemy=(30.0, 0.0)))
        self.assertTrue(any("enemy 7 is within" in d for d in v["diagnostics"]), v["diagnostics"])
        self.assertNotEqual(v["result"], "pass")

    def test_a_jump_press_and_release_are_not_contacts(self):
        v = judge("player_dx_px", run(+1, jump_at=60), run(-1, jump_at=60))
        self.assertFalse(any("clear window ends" in d for d in v["diagnostics"]), v["diagnostics"])

    def test_a_wall_the_player_starts_against_looks_like_a_player_that_cannot_move(self):
        # The trace has no geometry: a body that never starts moving gives no contact to see, so this
        # fails. On a clean game that is a failure on the reference, and the validity rule drops the check.
        v = judge("player_dx_px", run(+1), run(-1, wall=0.0))
        self.assertEqual(v["result"], "fail", v)

    def test_a_contact_on_the_first_mirrored_tick_leaves_nothing_to_judge(self):
        v = judge("player_dx_px", run(+1, enemy=(0.0, 0.0), press=10), run(-1, enemy=(0.0, 0.0), press=10))
        self.assertEqual(v["result"], "not_exercised", v)
        self.assertIn("not exercised: the clear window holds no tick after the first mirrored input", v["diagnostics"])


class NeverAPassByDefault(unittest.TestCase):
    def test_a_player_that_does_not_move_is_not_exercised(self):
        v = judge("player_dx_px", run(+1, speed=0.0), run(-1, speed=0.0))
        self.assertEqual(v["result"], "not_exercised")
        self.assertTrue(any("moved 0.0 px" in d for d in v["diagnostics"]))

    def test_an_equal_signal_that_is_zero_on_both_is_not_exercised(self):
        self.assertEqual(judge("max_rise_px", run(+1), run(-1))["result"], "not_exercised")

    def test_a_twin_that_is_not_the_mirror_cannot_tell(self):
        v = judge("player_dx_px", run(+1), run(+1, eid="r2"))
        self.assertEqual(v["result"], "insufficient_observation")
        self.assertEqual(v["applicable"], "unknown")
        self.assertIn("cannot tell: the twin's inputs are not the left probe's inputs mirrored", v["diagnostics"])

    def test_a_trace_with_no_floor_state_cannot_tell(self):
        left, right = run(+1), run(-1)
        for ep in (left, right):
            ep["capabilities"]["onFloor"] = False
        v = judge("player_dx_px", left, right)
        self.assertEqual((v["result"], v["applicable"]), ("insufficient_observation", "unknown"))

    def test_a_missing_twin_is_an_error(self):
        s = spec(op())
        self.assertEqual(evaluate(s, run(+1))["result"], "execution_error")


class Contract(unittest.TestCase):
    def test_the_example_validates(self):
        doc = json.loads((REPO / "contracts/examples/trace-spec-metamorphic.v1.json").read_text())
        validate_v1(doc, "trace-spec")
        self.assertEqual(doc["operation"]["type"], "metamorphic")

    def test_only_sideways_travel_negates_and_only_the_others_stay_equal(self):
        for signal, relation in (("max_rise_px", "negate"), ("player_dx_px", "equal"), ("facing_flips", "equal")):
            with self.subTest(signal=signal, relation=relation):
                bad = spec(dict(op(), signal=signal, relation=relation))
                with self.assertRaises(ContractError):
                    validate_v1(bad, "trace-spec")

    def test_the_bounds_are_not_in_the_spec(self):
        bad = spec(dict(op(), enemyClearPx=1.0))
        with self.assertRaises(ContractError):
            validate_v1(bad, "trace-spec")


class Derivation(unittest.TestCase):
    ACTIONS = ["move_left", "move_right", "jump", "shoot"]

    def test_the_mirror_swaps_each_paired_action_and_twice_is_the_original(self):
        program = {"op": "sequence", "steps": [{"op": "hold", "action": "move_right", "durationTicks": 40},
                                               {"op": "tap", "action": "jump", "durationTicks": 4}]}
        once = metamorphic.mirror_program(program, PAIRS)
        self.assertEqual(once["steps"][0]["action"], "move_left")
        self.assertEqual(once["steps"][1]["action"], "jump")
        self.assertEqual(metamorphic.mirror_program(once, PAIRS), program)

    def test_what_cannot_be_mirrored_is_cannot_tell(self):
        jump_only = {"op": "tap", "action": "jump", "durationTicks": 4}
        with self.assertRaisesRegex(metamorphic.NoMirror, "changes nothing"):
            metamorphic.mirror_program(jump_only, PAIRS)
        sided = {"op": "sequence", "steps": [{"op": "hold", "action": "move_right", "durationTicks": 4},
                                             {"op": "tap", "action": "aim_left", "durationTicks": 4}]}
        with self.assertRaisesRegex(metamorphic.NoMirror, "aim_left names a side"):
            metamorphic.mirror_program(sided, PAIRS)
        with self.assertRaisesRegex(metamorphic.NoMirror, "no left/right pair"):
            metamorphic.mirror_program(jump_only, metamorphic.pairs_for(["jump"]))

    def test_derive_gives_one_valid_check_per_signal(self):
        probe = {"id": "jump-w40-x2", "family": "jump-taps", "description": "Walk right, jump.",
                 "program": {"op": "hold", "action": "move_right", "durationTicks": 40}, "tags": ["no-shoot"]}
        d = metamorphic.derive(probe, self.ACTIONS)
        self.assertIsNone(d["reason"])
        self.assertEqual(d["mirror"]["id"], "jump-w40-x2-mirror")
        self.assertEqual([e["spec"]["operation"]["signal"] for e in d["entries"]], list(MIRROR_SIGNALS))
        for e in d["entries"]:
            validate_v1(e["spec"], "trace-spec")
            self.assertFalse(e["approved"])
            self.assertEqual(e["applies"], {"kind": "pair", "left": "jump-w40-x2", "right": "jump-w40-x2-mirror"})

    def test_the_library_probes_that_have_a_mirror(self):
        from expectrail.jit.probes import jit_library

        derived = [metamorphic.derive(p, self.ACTIONS) for p in jit_library(self.ACTIONS)]
        none = sorted(d["probe"] for d in derived if d["mirror"] is None)
        self.assertEqual(none, ["jump-w0-x1", "jump-w0-x2", "jump-w0-x8", "shoot-right-every12",
                                "shoot-right-every48", "wait-long"])
        self.assertEqual(sum(d["mirror"] is not None for d in derived), 19)

    def test_a_mirrored_probe_compiles_to_a_route(self):
        from expectrail.discovery.route_compiler import compile_route
        from expectrail.jit.probes import jit_library

        for p in jit_library(self.ACTIONS):
            d = metamorphic.derive(p, self.ACTIONS)
            if d["mirror"]:
                compile_route(d["mirror"]["program"], name=d["mirror"]["id"], description="m", actions=self.ACTIONS)


class PublicTool(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(REPO / "tools"))
        import metamorphic_public
        self.tool = metamorphic_public

    def test_twin_pairs_that_are_the_same_two_programs_are_measured_once(self):
        profile = json.loads((REPO / "discovery/platformer.profile.json").read_text())
        pairs, routes, skipped = self.tool.checks(profile)
        self.assertEqual(len(pairs), 14)
        self.assertEqual(len(routes), 28)
        self.assertIn({"probe": "hold-left", "reason": "the same two programs as a pair already measured"}, skipped)

    def test_a_held_out_patch_is_refused(self):
        import tempfile
        from expectrail.jit import bench

        fake = {"defects": [{"id": "x", "family": "f", "patch": "bench/jit/fresh-9/x/defect.patch"}]}
        profile = json.loads((REPO / "discovery/platformer.profile.json").read_text())
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(bench, "public_cases", return_value=fake):
            with self.assertRaisesRegex(ValueError, "public-only"):
                self.tool.builds(REPO / "game/platformer", profile, Path(tmp))

    def test_the_summary_keeps_only_usable_checks_that_do_not_pass_the_control(self):
        rows = [{"check": "a", "left": "p", "right": "q", "signal": "player_dx_px", "usable": True,
                 "control": "indeterminate", "kept": True, "catches": ["slow-left"],
                 "runs": {"clean": ["pass"] * 3, "do-nothing": ["not_exercised"] * 3, "slow-left": ["fail"]}},
                {"check": "b", "left": "p", "right": "q", "signal": "max_rise_px", "usable": True,
                 "control": "passes", "kept": False, "catches": ["slow-left"],
                 "runs": {"clean": ["pass"] * 3, "do-nothing": ["pass"] * 3, "slow-left": ["fail"]}}]
        doc = {"pairs": [{"left": "p", "right": "q"}], "skipped": [], "evidence": {}, "rows": rows,
               "builds": [{"id": "clean", "kind": "clean"}, {"id": "do-nothing", "kind": "control"},
                          {"id": "slow-left", "kind": "defect", "family": "movement-input"}]}
        s = self.tool.summary(doc)
        self.assertEqual((s["kept"], s["defectsCaught"], s["caughtBy"]), (1, ["slow-left"], {"slow-left": ["a"]}))
        self.assertIn("1 of 1", self.tool.markdown(copy.deepcopy(doc), "4.7.2"))


if __name__ == "__main__":
    unittest.main()
