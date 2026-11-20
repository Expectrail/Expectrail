"""The overnight loop's review against the failing base: off by default, and never the loop's decision."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tests.test_review_change as stand_ins  # installs Z1/Z4 stand-ins until those modules land
from agents.demo_loop import annotation
from agents.loop import one_run
from agents.report import ILLUSTRATIVE_NOTE
from harness.run import REPO

FIXTURES = REPO / "agents" / "fixtures"
SECTION = "## Review against the failing base"


class ReviewInTheLoopTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "loop"
        patcher = mock.patch("agents.review_change.validate", side_effect=stand_ins._validate)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_loop(self, flag: str | None) -> tuple[dict, str]:
        env = {"EXPECTRAIL_HELDOUT_DIR": "", "EXPECTRAIL_OBS_PROVIDER": "trace"}
        if flag is not None:
            env["EXPECTRAIL_REVIEW"] = flag
        with mock.patch.dict(os.environ, env):
            if flag is None:
                os.environ.pop("EXPECTRAIL_REVIEW", None)
            result = one_run(self.root, use_muse=False, offline_triage=True, observations=FIXTURES / "obs-fixed.json",
                             candidate_patch=FIXTURES / "fix-collision-mask.patch", skip_harness=True, run_trust=False)
        return result, (self.root / "morning" / "morning-report.md").read_text(encoding="utf-8")

    def test_off_by_default_nothing_changes(self):
        result, report = self.run_loop(None)
        self.assertEqual(result["decision"], "accept")
        self.assertNotIn("review", result)
        self.assertNotIn("review", result["morning"])
        self.assertFalse((self.root / "review").exists())
        self.assertNotIn(SECTION, report)

    def test_on_the_review_is_reported_beside_the_decision(self):
        result, report = self.run_loop("on")
        self.assertEqual(result["decision"], "accept")
        self.assertEqual(result["review"]["status"], "REPAIR DEMONSTRATED")
        self.assertEqual(result["review"]["evidenceLabel"], "SAMPLE")
        self.assertEqual(result["morning"]["review"]["status"], "REPAIR DEMONSTRATED")
        record = json.loads((self.root / "review" / "change-evidence.json").read_text())
        self.assertTrue([s for s in record["stages"] if s["stage"] == "candidate"][0]["reused"])  # no second verify
        self.assertEqual(record["candidate"]["origin"], "fixture")
        self.assertIn(SECTION, report)
        self.assertIn(ILLUSTRATIVE_NOTE, report)  # a sample review has no frames, so the fixtures stay labelled

    def test_a_failed_review_never_changes_the_decision(self):
        with mock.patch("agents.review_change.review", side_effect=RuntimeError("boom")):
            result, report = self.run_loop("on")
        self.assertEqual(result["decision"], "accept")
        self.assertEqual(result["review"]["status"], "INCONCLUSIVE")
        self.assertTrue((self.root / "review" / "review-error.txt").is_file())
        self.assertIn(SECTION, report)

    def test_the_review_s_own_frames_replace_the_fixtures(self):
        def fake_review(_request, _candidate, out, **_kw):
            (out / "assets").mkdir(parents=True)
            for name in ("base", "candidate"):
                (out / "assets" / f"{name}.png").write_bytes(stand_ins.PNG)
            frame = {"frame": 30, "sha256": "0" * 64}
            return {"status": "REPAIR DEMONSTRATED", "evidenceLabel": "FRESH LIVE", "reasons": [],
                    "arms": {"base": {"frame": dict(frame, path="assets/base.png")},
                             "candidate": {"frame": dict(frame, path="assets/candidate.png")}}}

        with mock.patch("agents.review_change.review", side_effect=fake_review):
            result, report = self.run_loop("on")
        self.assertNotIn(ILLUSTRATIVE_NOTE, report)
        sources = [Path(f["source"]).name for f in result["morning"]["frames"]]
        self.assertEqual(sources, ["base.png", "candidate.png"])
        # The fake review wrote no record, so the page cannot be drawn: that is recorded and the
        # review's own result stands.
        self.assertEqual(result["review"]["status"], "REPAIR DEMONSTRATED")
        self.assertIsNone(result["review"]["html"])
        self.assertTrue((self.root / "review" / "render-error.txt").is_file())

    def test_the_demo_annotation_keeps_its_parsed_line_and_adds_the_review_on_its_own(self):
        row = {"run": 3, "decision": "accept", "attempts": ["accept"], "triageSource": "wonder", "fixerSource": "muse",
               "trustOk": True, "verificationProvenance": "harness", "signed": True, "wallClockSeconds": 700.0,
               "samImages": 0, "review": {"status": "REPAIR DEMONSTRATED", "evidenceLabel": "FRESH LIVE", "reasons": []}}
        lines = annotation(row).splitlines()
        plain = annotation({k: v for k, v in row.items() if k != "review"})
        self.assertEqual(lines[0], plain)
        self.assertEqual(lines[1], "::notice title=Demo run 3 review::REPAIR DEMONSTRATED; FRESH LIVE; none")


if __name__ == "__main__":
    unittest.main()
