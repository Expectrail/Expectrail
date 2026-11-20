"""agents.review_change: the failing base and the candidate on the same checks, and what may be claimed.

Until expectrail.change_evidence (Z1) and expectrail.diagnostics (Z4) land, small stand-ins with the
agreed interface are installed for these tests only; once the real modules exist they are used.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from expectrail import contracts
from harness.run import REPO
from tests.test_agents import _held_out_dir, _request, _walk_trace

FIXTURES = REPO / "agents" / "fixtures"
SEED = REPO / "bugs" / "physics-fall-through" / "v1.patch"
FIX = FIXTURES / "fix-collision-mask.patch"


def _install_stand_ins() -> None:
    try:
        import expectrail.change_evidence  # noqa: F401
    except ImportError:
        ce = types.ModuleType("expectrail.change_evidence")
        table = {("fail", "pass"): "REPAIRED", ("pass", "pass"): "PRESERVED",
                 ("pass", "fail"): "REGRESSION", ("fail", "fail"): "UNRESOLVED"}
        ce.FORMAT = "expectrail.change-evidence/v0"
        ce.compare = lambda before, after: table.get((before, after), "INCONCLUSIVE")

        def pair(base_checks, candidate_checks, *, primary, base_ids, candidate_ids):
            after = {(c["spec"], c["route"]): c["result"] for c in candidate_checks}
            return [{"spec": b["spec"], "kind": b["kind"], "route": b["route"], "primary": b["spec"] in primary,
                     "required": True, "before": b["result"], "after": after.get((b["spec"], b["route"])),
                     "comparison": (ce.compare(b["result"], after.get((b["spec"], b["route"])))
                                    if base_ids == candidate_ids else "INCONCLUSIVE")} for b in base_checks]

        def review_status(rows, verification):
            primary = [r for r in rows if r["primary"]]
            if verification["decision"] == "reject":
                return "REJECTED", ["the verifier rejected the candidate"]
            if verification["decision"] != "accept" or not primary or any(
                    r["comparison"] == "INCONCLUSIVE" for r in primary):
                return "INCONCLUSIVE", ["a required comparison is incomplete"]
            if any(r["comparison"] == "REPAIRED" for r in primary):
                return "REPAIR DEMONSTRATED", []
            return "NO REPAIR DEMONSTRATED", ["no requested claim went from FAIL to PASS"]

        ce.pair, ce.review_status = pair, review_status
        sys.modules["expectrail.change_evidence"] = ce
    try:
        import expectrail.diagnostics  # noqa: F401
    except ImportError:
        dg = types.ModuleType("expectrail.diagnostics")
        dg.classify = lambda exc=None, *, stage, detail="": {
            "code": "EXECUTION_TIMEOUT" if isinstance(exc, TimeoutError) else "OBSERVATION_INVALID",
            "stage": stage, "detail": detail, "fix": "see the stage's error file"}
        sys.modules["expectrail.diagnostics"] = dg


_install_stand_ins()
_real_validate = contracts.validate


def _validate(doc, kind=None):
    """The change-evidence schema arrives with Z1; until then only its format is checked here."""
    if kind == "change-evidence" and kind not in contracts.KINDS:
        assert doc["format"] == "expectrail.change-evidence/v0"
        return kind
    return _real_validate(doc, kind)


from agents import review_change  # noqa: E402  (after the stand-ins)
from agents.review_change import EXIT, review  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
       b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def _fake_harness(_route, out, patches=None, **_kw):
    """Without Godot: the clean game and seed plus fix walk; the seed alone falls through."""
    out.mkdir(parents=True, exist_ok=True)
    names = [Path(p).name for p in patches or []]
    if names == [SEED.name]:
        (out / "trace.json").write_text((FIXTURES / "trace-fallthrough.json").read_text())
    else:
        (out / "trace.json").write_text(json.dumps(_walk_trace(frozen=False)))
    (out / "replay.json").write_text(json.dumps({"patches": names}) + "\n")
    (out / "frames").mkdir(exist_ok=True)
    for i in range(0, 61, 2):
        (out / "frames" / f"f{i:08d}.png").write_bytes(PNG)



# These historical fixtures exercise the explicit engine-only benchmark control.
# Default two-observer verdicts are covered by test_default_vision and test_two_observers.
def setUpModule():
    global _trace_control
    _trace_control = mock.patch.dict("os.environ", {"EXPECTRAIL_OBS_PROVIDER": "trace"})
    _trace_control.start()


def tearDownModule():
    _trace_control.stop()


class _Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        patcher = mock.patch("agents.review_change.validate", side_effect=_validate)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {"EXPECTRAIL_HELDOUT_DIR": "", "EXPECTRAIL_OBS_PROVIDER": "trace"})
        env.start()
        self.addCleanup(env.stop)

    def sample(self, candidate: Path, base_obs: str, obs: str, **kw) -> dict:
        return review(_request(), candidate, self.tmp / "review", mode="sample",
                      base_observations=FIXTURES / base_obs, observations=FIXTURES / obs, **kw)

    def written(self) -> dict:
        return json.loads((self.tmp / "review" / "change-evidence.json").read_text())


class SampleModeTest(_Base):
    def test_the_correct_fix_is_a_demonstrated_repair(self):
        rec = self.sample(FIX, "obs-fallthrough.json", "obs-fixed.json")
        self.assertEqual(rec["status"], "REPAIR DEMONSTRATED")
        self.assertEqual(EXIT[rec["status"]], 0)
        self.assertEqual(rec["evidenceLabel"], "SAMPLE")
        self.assertEqual(rec["candidate"]["origin"], "fixture")  # a fixture is never called a model repair
        primary = [r for r in rec["rows"] if r["primary"]]
        self.assertEqual([(r["before"], r["after"], r["comparison"]) for r in primary], [("fail", "pass", "REPAIRED")])
        self.assertEqual(rec, self.written())

    def test_a_fix_that_freezes_the_robot_is_rejected(self):
        rec = self.sample(FIXTURES / "freeze-player.patch", "obs-fallthrough.json", "obs-freeze.json")
        self.assertEqual(rec["status"], "REJECTED")
        self.assertEqual(EXIT[rec["status"]], 1)
        self.assertEqual(rec["verification"]["decision"], "reject")

    def test_nothing_failing_before_means_no_repair_shown_even_when_the_verifier_accepts(self):
        rec = self.sample(FIX, "obs-fixed.json", "obs-fixed.json")
        self.assertEqual(rec["verification"]["decision"], "accept")
        self.assertEqual(rec["status"], "NO REPAIR DEMONSTRATED")
        self.assertEqual(EXIT[rec["status"]], 1)

    def test_a_patch_outside_the_editable_paths_is_rejected_before_anything_runs(self):
        with mock.patch("agents.verifier.verify") as verify:
            rec = self.sample(FIXTURES / "out-of-glob.patch", "obs-fallthrough.json", "obs-fixed.json")
        verify.assert_not_called()
        self.assertEqual(rec["status"], "REJECTED")
        self.assertEqual(rec["diagnostics"][0]["code"], "PATCH_SCOPE_BLOCKED")
        self.assertEqual([s["status"] for s in rec["stages"]][:4], ["failed", "skipped", "skipped", "skipped"])
        self.assertEqual(rec["rows"], [])

    def test_an_existing_review_is_never_overwritten(self):
        self.sample(FIX, "obs-fallthrough.json", "obs-fixed.json")
        first = (self.tmp / "review" / "change-evidence.json").read_text()
        rec = self.sample(FIX, "obs-fallthrough.json", "obs-fixed.json")
        self.assertEqual(rec["status"], "INCONCLUSIVE")
        self.assertEqual(rec["diagnostics"][0]["code"], "INPUT_INVALID")
        self.assertEqual((self.tmp / "review" / "change-evidence.json").read_text(), first)

    def test_a_verification_for_another_patch_is_not_reused(self):
        from agents.verifier import verify

        verify(_request(), FIXTURES / "freeze-player.patch", self.tmp / "old",
               observations_path=FIXTURES / "obs-freeze.json", skip_harness=True)
        rec = self.sample(FIX, "obs-fallthrough.json", "obs-fixed.json",
                          verification_path=self.tmp / "old" / "verification.json")
        self.assertEqual(rec["status"], "INCONCLUSIVE")
        self.assertIn("EVIDENCE_MISMATCH", [d["code"] for d in rec["diagnostics"]])
        self.assertEqual(rec["rows"], [])

    def test_a_bound_verification_is_reused(self):
        from agents.verifier import verify

        verify(_request(), FIX, self.tmp / "old", observations_path=FIXTURES / "obs-fixed.json", skip_harness=True)
        with mock.patch("agents.verifier.verify") as again:
            rec = self.sample(FIX, "obs-fallthrough.json", "obs-fixed.json",
                              verification_path=self.tmp / "old" / "verification.json")
        again.assert_not_called()
        self.assertEqual(rec["status"], "REPAIR DEMONSTRATED")
        self.assertTrue([s for s in rec["stages"] if s["stage"] == "candidate"][0]["reused"])


class LiveModeTest(_Base):
    def live(self, **env) -> dict:
        with (mock.patch.dict(os.environ, env),
              mock.patch("agents.verifier.harness_run", side_effect=_fake_harness),
              mock.patch("harness.run.find_godot", return_value=Path("/usr/bin/true"))):
            return review(_request(), FIX, self.tmp / "review", mode="live")

    def test_with_the_private_routes_the_repair_is_fresh_live_and_names_no_private_route(self):
        rec = self.live(EXPECTRAIL_HELDOUT_DIR=str(_held_out_dir(self.tmp)))
        self.assertEqual(rec["status"], "REPAIR DEMONSTRATED", rec["reasons"])
        self.assertEqual(rec["evidenceLabel"], "FRESH LIVE")
        self.assertEqual(rec["private"], {"source": "harness", "checks": 1, "passed": 1, "failed": 0, "needsReview": 0})
        self.assertNotIn("held-out-test", json.dumps(rec))  # the private route's name
        base, cand = rec["arms"]["base"], rec["arms"]["candidate"]
        self.assertEqual(base["frame"]["frame"], cand["frame"]["frame"])  # the same moment, before and after
        for arm in (base, cand):
            self.assertTrue((self.tmp / "review" / arm["frame"]["path"]).is_file())
        self.assertNotEqual(base["replaySha256"], cand["replaySha256"])

    def test_without_the_private_routes_a_live_repair_is_not_claimed(self):
        rec = self.live()
        self.assertEqual(rec["status"], "INCONCLUSIVE")
        self.assertEqual(rec["evidenceLabel"], "MIXED OR INCOMPLETE")
        self.assertIn("PRIVATE_SUITE_UNAVAILABLE", [d["code"] for d in rec["diagnostics"]])
        self.assertEqual(EXIT[rec["status"]], 2)

    def test_without_godot_nothing_runs_and_it_says_why(self):
        with mock.patch("harness.run.find_godot", side_effect=SystemExit("no godot here")):
            rec = review(_request(), FIX, self.tmp / "review", mode="live")
        self.assertEqual(rec["status"], "INCONCLUSIVE")
        self.assertEqual(rec["diagnostics"][0]["code"], "TOOL_MISSING")

    def test_a_crash_in_an_arm_leaves_a_record_and_no_invented_comparison(self):
        boom = TimeoutError(f"replay timed out in {REPO}/runs with key msk-{'A' * 40}")
        with mock.patch("agents.verifier.public_route_checks", side_effect=boom):
            rec = self.live(EXPECTRAIL_HELDOUT_DIR=str(_held_out_dir(self.tmp)))
        self.assertEqual(rec["status"], "INCONCLUSIVE")
        self.assertEqual(rec["rows"], [])
        self.assertIsNone(rec["arms"]["base"])
        detail = rec["diagnostics"][0]["detail"]
        self.assertNotIn(str(REPO), detail)
        self.assertNotIn("msk-AAAA", detail)
        self.assertTrue((self.tmp / "review" / "base-error.txt").is_file())


class CommandTest(_Base):
    def test_exit_status_follows_the_review(self):
        req = self.tmp / "rr.json"
        req.write_text(json.dumps(_request()))
        code = review_change.main(["--request", str(req), "--candidate", str(FIX), "--out", str(self.tmp / "review"),
                                   "--mode", "sample", "--base-observations", str(FIXTURES / "obs-fallthrough.json"),
                                   "--observations", str(FIXTURES / "obs-fixed.json")])
        self.assertEqual(code, 0)
        self.assertEqual(self.written()["status"], "REPAIR DEMONSTRATED")


if __name__ == "__main__":
    unittest.main()
