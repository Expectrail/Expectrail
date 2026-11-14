"""Release gate, coverage (#258): an empty suite, an unreachable route, zero evaluations, a skipped
required observer, a missing private suite.

Each test replays the bundled game with real Godot and asserts that clearance is not granted, and,
where the same run without the fault is cleared, shows that too, so the fault is what stopped it.

``test_a_route_whose_inputs_the_game_does_not_have_is_not_clearance`` is a probe of a control that is
not defended today (#417): it is an expected failure until the gate notices a route that drives
nothing and says so. When it starts to pass, the suite fails on the unexpected success: then remove the decorator
and the row's ``open`` reason in ``controls.py``.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from expectrail.gate import verify as gate
from tests.release_gate.common import GAME, REPO, ROUTE, SPEC_FILE, SPECS, GateCase, edit_json


class CoverageTest(GateCase):
    def test_no_approved_spec_at_all_is_not_clearance(self):
        head = self.copy("no-spec")
        (head / SPEC_FILE).unlink()
        code, status, err = self.verify(head)
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["decision"]), (2, "needs-review"))
        self.assertIn("no checks ran", status["reasons"])

    def test_specs_that_are_all_drafts_judge_nothing_and_are_not_clearance(self):
        head = self.copy("drafts")
        edit_json(head / SPEC_FILE, lambda doc: doc.pop("approval"))
        code, status, err = self.verify(head)
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["decision"]), (2, "needs-review"))
        self.assertIn("no checks ran", status["reasons"])

    def test_a_route_pattern_that_matches_no_file_is_not_clearance(self):
        code, status, err = self.verify(self.clean, routes="harness/routes/no-such-route*.json")
        self.assertNotCleared(code, status, err)
        self.assertEqual((code, status["decision"]), (2, "needs-review"))
        self.assertTrue(any("no route files match" in r for r in status["reasons"]), status["reasons"])

    @unittest.expectedFailure   # #417: today this run is accepted
    def test_a_route_whose_inputs_the_game_does_not_have_is_not_clearance(self):
        head = self.copy("unknown-actions")

        def rename(route):
            for event in route["events"]:
                event["action"] = "teleport_through_wall"   # no such action in the game's input map

        edit_json(head / ROUTE, rename)
        code, status, err = self.verify(head)
        self.assertNotCleared(code, status, err)
        # Not cleared is not enough here: the recorded observer has no answers for the frames of a
        # player who never moved, so this run needs review for that reason alone, and a live observer
        # would see a robot above the ground and pass. The defence is the gate saying why.
        said = " ".join(status["reasons"] + [d["detail"] for d in status["diagnostics"]])
        self.assertIn("teleport_through_wall", said, "the job does not say the route names an action the game lacks")

    def test_under_two_observers_a_missing_visual_observer_is_not_clearance(self):
        # The gate itself, in this process, on a real replay: the command line has no switch for the
        # rule yet (#379). Engine-only on the same game accepts, so the missing observer is the reason.
        documents = {}
        for rule in (gate.rec.ENGINE_ONLY, gate.rec.BOTH):
            documents[rule] = gate.run_gate(repo=self.clean, game=GAME, routes=[ROUTE], specs=SPECS,
                                            out=self.tmp / f"out-{rule}", work=self.tmp / f"work-{rule}",
                                            rule=rule, visual=None)
        self.assertEqual(documents[gate.rec.ENGINE_ONLY]["decision"], "accept")
        self.assertNotEqual(documents[gate.rec.BOTH]["decision"], "accept")
        self.assertEqual(documents[gate.rec.BOTH]["decision"], "needs-review")

    def test_held_out_routes_that_cannot_be_read_are_not_clearance(self):
        # A folder that is not there stands for held-out routes this job could not get. No held-out
        # material is read here or anywhere in this suite.
        results = {}
        for name, extra in (("without", []), ("unreadable", ["--heldout", str(self.tmp / "not-there")])):
            out = self.tmp / f"gate-{name}"
            done = subprocess.run([sys.executable, "-m", "expectrail.gate.verify", "--repo", str(self.clean),
                                   "--game", GAME, "--routes", ROUTE, "--specs", SPECS, "--out", str(out), *extra],
                                  cwd=REPO, capture_output=True, text=True, timeout=300)
            results[name] = (done.returncode, json.loads((out / "findings.json").read_text(encoding="utf-8")))
        self.assertEqual((results["without"][0], results["without"][1]["decision"]), (0, "accept"))
        code, document = results["unreadable"]
        self.assertNotEqual(code, 0)
        self.assertEqual((document["decision"], document["heldOut"]["status"]), ("needs-review", "unavailable"))
