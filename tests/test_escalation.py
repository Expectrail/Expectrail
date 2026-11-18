"""Report first, evidence on rejection (agents/escalation.py, docs/report-first.md)."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.escalation as esc
import agents.matrix as matrix
from agents.loop import one_run
from agents.orchestrator import build_repair_request
from agents.verifier import verify as real_verify
from expectrail.contracts import load
from harness.run import REPO

FIXTURES = REPO / "agents" / "fixtures"
SPEC = load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec")


def request() -> dict:
    return build_repair_request(
        request_id="rr-escalation-test", spec=SPEC,
        verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
        route=load(REPO / "harness" / "routes" / "smoke.json", "route"),
        base_patch="bugs/physics-fall-through/v1.patch", editable=["player/**"], attempts=3)


def files(tmp: Path) -> dict:
    run = tmp / "run"
    (run / "frames").mkdir(parents=True)
    for i in range(120):
        (run / "frames" / f"f{i:08d}.png").write_bytes(b"")
    (run / "godot.log").write_text("log\n")
    route = tmp / "route.json"
    route.write_text("{}\n")
    return esc.report_files(run, route)


REJECTED = {"decision": "reject", "checks": [
    {"kind": "regression", "spec": "player-stays-above-ground", "route": "smoke", "result": "fail"},
    {"kind": "gameplay", "spec": "player-motion-on-smoke", "route": "smoke", "result": "pass"},
    {"kind": "held-out", "spec": "player-stays-above-ground", "route": "held-out-routes", "result": "fail"},
]}



# Historical trace fixtures: explicitly select the diagnostic benchmark control.
def setUpModule():
    global _trace_control
    _trace_control = mock.patch.dict("os.environ", {"EXPECTRAIL_OBS_PROVIDER": "trace"})
    _trace_control.start()


def tearDownModule():
    _trace_control.stop()


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.files = files(Path(self.tmp.name))
        self.env = mock.patch.dict(os.environ, {esc.ENV: ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_the_report_has_six_screenshots_spaced_over_the_run_the_route_and_the_log(self):
        shots = sorted(k for k in self.files if "/screenshots/" in k)
        self.assertEqual(len(shots), esc.SHOTS)
        self.assertTrue(shots[0].endswith("f00000000.png") and shots[-1].endswith("f00000119.png"))
        self.assertIn("bug-report/route.json", self.files)
        self.assertIn("bug-report/godot.log", self.files)

    def test_attempt_one_gets_the_report_and_no_evidence(self):
        brief, stage = esc.briefing(request(), self.files, 1, rejected_before=False)
        self.assertEqual(stage, "report")
        self.assertFalse(brief["withRequest"])
        self.assertIn(SPEC["instruction"], brief["prompt"])
        for evidence in ("Spec id", "Assertion", "Verdict", "First fail frame", "repair-request.json"):
            self.assertNotIn(evidence, brief["prompt"])

    def test_an_attempt_with_no_fix_escalates_too(self):
        # Oct 31: report-only attempts on both sinking bugs timed out three times running; the
        # evidence fixed each on the first attempt. No fix is a failed attempt.
        brief, stage = esc.briefing(request(), self.files, 2, rejected_before=False, empty_before=True)
        self.assertEqual(stage, "evidence")
        self.assertTrue(brief["withRequest"])

    def test_after_a_rejection_the_next_attempt_gets_the_evidence(self):
        brief, stage = esc.briefing(request(), self.files, 2, rejected_before=True)
        self.assertEqual(stage, "evidence")
        self.assertTrue(brief["withRequest"])
        self.assertIn("Spec id: player-stays-above-ground", brief["prompt"])
        self.assertIn("bug-report/screenshots/", brief["prompt"])

    def test_without_screenshots_the_fixer_starts_from_the_evidence(self):
        self.assertEqual(esc.briefing(request(), None, 1, rejected_before=False), (None, "evidence"))

    def test_the_old_behaviour_is_one_setting_away(self):
        with mock.patch.dict(os.environ, {esc.ENV: "evidence"}):
            self.assertEqual(esc.briefing(request(), self.files, 1, rejected_before=False)[1], "evidence")
        with mock.patch.dict(os.environ, {esc.ENV: "screenshots-only"}), self.assertRaises(SystemExit):
            esc.mode()

    def test_feedback_names_public_checks_only(self):
        fb = esc.public_feedback(REJECTED, 1)
        self.assertEqual(fb["reasons"], ["regression check player-stays-above-ground failed on smoke"])
        self.assertNotIn("held-out", json.dumps(fb))

    def test_a_rejection_only_held_out_routes_saw_says_nothing_about_them(self):
        only_private = {"decision": "reject", "checks": [c for c in REJECTED["checks"] if c["kind"] != "regression"]}
        fb = esc.public_feedback(only_private, 2)
        self.assertEqual(fb["reasons"], ["the attempt did not pass Expectrail's checks"])
        self.assertNotIn("held-out", json.dumps(fb))


class LoopEscalationTest(unittest.TestCase):
    """The overnight loop with Muse replaced: report first, evidence only after a verifier rejection,
    every candidate verified."""

    def test_report_then_empty_then_evidence_rejected_then_evidence_accepted(self):
        calls, verified = [], []
        outcomes = ["empty", "reject", "accept"]

        def fixer(req, out, *, briefing=None, prior_reject=None, **kwargs):
            calls.append({"briefing": briefing, "prior": prior_reject})
            out.mkdir(parents=True, exist_ok=True)
            (out / "fixer-work" / "player").mkdir(parents=True, exist_ok=True)
            if outcomes[len(calls) - 1] == "empty":
                return {"source": "muse", "empty": True, "ok": False}
            shutil.copy2(FIXTURES / "fix-collision-mask.patch", out / "candidate.patch")
            return {"source": "muse", "patchSha256": "0" * 64}

        def verifier(req, candidate, out, **kwargs):
            verified.append(candidate)
            if outcomes[len(calls) - 1] == "reject":
                out.mkdir(parents=True, exist_ok=True)
                (out / "verification.json").write_text(json.dumps(REJECTED))
                return REJECTED
            return real_verify(req, candidate, out, observations_path=FIXTURES / "obs-fixed.json", skip_harness=True)

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {esc.ENV: ""}), \
                mock.patch("agents.loop.run_fixer", fixer), \
                mock.patch("agents.loop.verify", verifier), \
                mock.patch("agents.loop.render_report", lambda req, out: files(Path(tmp))):
            result = one_run(Path(tmp) / "loop", use_muse=True, offline_triage=True,
                             observations=FIXTURES / "obs-fixed.json", candidate_patch=None,
                             skip_harness=True, run_trust=False)
        self.assertEqual(result["decision"], "accept")
        self.assertEqual([a["briefing"] for a in result["attempts"]], ["report", "evidence", "evidence"])
        self.assertEqual([a["decision"] for a in result["attempts"]], ["retry-empty", "reject", "accept"])
        self.assertEqual(len(verified), 2)  # every candidate, and only candidates, were verified
        self.assertFalse(calls[0]["briefing"]["withRequest"])
        self.assertIsNone(calls[0]["prior"])
        self.assertTrue(calls[1]["briefing"]["withRequest"])  # no fix is a failed attempt: escalate
        self.assertEqual(calls[1]["prior"]["reason"], "empty-patch")
        self.assertTrue(calls[2]["briefing"]["withRequest"])
        self.assertEqual(calls[2]["prior"]["reasons"], ["regression check player-stays-above-ground failed on smoke"])


class MatrixTest(unittest.TestCase):
    def test_the_matrix_measures_the_policy_the_loop_ships(self):
        self.assertIn("escalate", matrix.CONDITIONS)
        yml = (REPO / ".github" / "workflows" / "fix-matrix.yml").read_text()
        self.assertIn("default: 'escalate,screenshots,expectrail'", yml)


if __name__ == "__main__":
    unittest.main()
