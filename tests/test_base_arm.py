"""The failing-base arm (agents.verifier.public_route_checks) judges exactly as verify() does.

The review compares the request's seed alone with seed plus candidate on the same checks. If the
base arm judged differently from the candidate's checks in verify(), a FAIL to PASS could come from
the judging rather than the patch, so these tests hold the two together in every mode: fixture
observations, harness replays, and SAM on.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.verifier import public_route_checks, public_route_identity, verify
from harness.run import REPO
from tests.test_agents import _request

FIXTURES = REPO / "agents" / "fixtures"
SEED = REPO / "bugs" / "physics-fall-through" / "v1.patch"
FIX = FIXTURES / "fix-collision-mask.patch"


def _fake_harness(_route, out, patches=None, **_kw):
    """A replay without Godot: the fixed trace when the fix is applied, the falling one otherwise."""
    out.mkdir(parents=True, exist_ok=True)
    names = [Path(p).name for p in patches or []]
    trace = "trace-fixed.json" if FIX.name in names else "trace-fallthrough.json"
    (out / "trace.json").write_text((FIXTURES / trace).read_text())
    (out / "replay.json").write_text(json.dumps({"patches": names}) + "\n")


def _public(checks: list[dict]) -> list[dict]:
    return [c for c in checks if c["kind"] in ("regression", "gameplay")]


def _sam_pass(specs, *_args, **_kwargs):
    return [(s, {"spec": s["id"], "result": "pass"}, None) for s in specs]



# These historical fixtures exercise the explicit engine-only benchmark control.
# Default two-observer verdicts are covered by test_default_vision and test_two_observers.
def setUpModule():
    global _trace_control
    _trace_control = mock.patch.dict("os.environ", {"EXPECTRAIL_OBS_PROVIDER": "trace"})
    _trace_control.start()


def tearDownModule():
    _trace_control.stop()


class BaseArmMatchesVerifyTest(unittest.TestCase):
    def test_fixture_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            obs = FIXTURES / "obs-fixed.json"
            doc = verify(_request(), FIX, tmp / "verify", observations_path=obs, skip_harness=True)
            checks, arm = public_route_checks(_request(), [SEED, FIX], tmp / "arm", observations_path=obs)
        self.assertEqual(checks, _public(doc["checks"]))
        self.assertEqual(arm["source"], "fixture")
        self.assertIsNone(arm["replaySha256"])

    def test_harness_replay(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("agents.verifier.harness_run", side_effect=_fake_harness):
            tmp = Path(tmp)
            doc = verify(_request(), FIX, tmp / "verify", skip_harness=False)
            checks, arm = public_route_checks(_request(), [SEED, FIX], tmp / "arm")
        self.assertEqual(checks, _public(doc["checks"]))
        self.assertEqual((arm["source"], arm["groundSource"]), ("harness", "engine"))

    def test_sam_on(self):
        with (tempfile.TemporaryDirectory() as tmp,
              mock.patch("agents.verifier.harness_run", side_effect=_fake_harness),
              mock.patch("agents.verifier.sam_on", return_value=True),
              mock.patch("agents.verifier._sam_verdicts", side_effect=_sam_pass)):
            tmp = Path(tmp)
            doc = verify(_request(), FIX, tmp / "verify", skip_harness=False)
            checks, arm = public_route_checks(_request(), [SEED, FIX], tmp / "arm")
        self.assertEqual(checks, _public(doc["checks"]))
        self.assertGreater(len([c for c in checks if c["kind"] == "regression"]), 1)  # the SAM specs too
        self.assertGreater(len(arm["identity"]["specs"]), 1)


class BaseArmTest(unittest.TestCase):
    def test_the_seed_alone_fails_where_seed_plus_fix_passes(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("agents.verifier.harness_run", side_effect=_fake_harness):
            tmp = Path(tmp)
            base, base_arm = public_route_checks(_request(), [SEED], tmp / "base")
            cand, cand_arm = public_route_checks(_request(), [SEED, FIX], tmp / "cand")
        self.assertEqual(base[0]["result"], "fail")
        self.assertEqual(cand[0]["result"], "pass")
        self.assertIsNotNone(base_arm["firstFailFrame"])
        self.assertIsNone(cand_arm["firstFailFrame"])
        self.assertNotEqual(base_arm["replaySha256"], cand_arm["replaySha256"])
        self.assertEqual(base_arm["identity"], cand_arm["identity"])  # judged the same way: comparable

    def test_missing_observations_are_needs_review_with_no_stand_in_digest(self):
        with (tempfile.TemporaryDirectory() as tmp,
              mock.patch("agents.verifier.harness_run", side_effect=_fake_harness),
              mock.patch("agents.verifier._ground_observations", side_effect=SystemExit("no observations"))):
            checks, arm = public_route_checks(_request(), [SEED], Path(tmp) / "base")
            self.assertTrue((Path(tmp) / "base" / "observations-error.txt").is_file())
        self.assertEqual(checks[0]["result"], "needs-review")
        self.assertEqual(arm["source"], "unavailable")
        self.assertIsNone(arm["observationsSha256"])

    def test_a_request_for_another_game_tree_is_refused(self):
        request = _request()
        request["base"]["tree"] = "0" * 64
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
            public_route_checks(request, [SEED], Path(tmp) / "base")

    def test_identity_changes_with_the_spec(self):
        request = _request()
        other = json.loads(json.dumps(request))
        other["failing"][0]["spec"]["description"] = "a different sentence"
        self.assertNotEqual(public_route_identity(request)["specs"], public_route_identity(other)["specs"])


if __name__ == "__main__":
    unittest.main()
